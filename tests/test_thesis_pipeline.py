"""
ThesisPipeline (S1–S5) 测试

用 FakeLLMClient + MockFinancialsProvider + MockTextProvider 离线验证：
五阶段产物落盘、定量环节用真实财报数据、无 proxy 环节进尽调队列且不编造、
认知差脊柱不变、整体失败回退单次投影。对应 P1 Step 7。
"""
from datetime import datetime

import pytest

from src.config.models import TargetConfig
from src.data_ingestion.financials import MockFinancialsProvider
from src.data_ingestion.models import QuoteData
from src.data_ingestion.text import MockTextProvider
from src.engines import GapCalculator, ThesisPipeline
from src.engines.thesis_pipeline import PipelineResult
from src.llm.models import (
    ConsensusResult,
    Evidence,
    LogicChain,
    LogicChainLink,
    ThesisProjection,
    ThesisProjectionResult,
)
from src.persistence import ArtifactStore
from tests.fakes import FakeLLMClient


@pytest.fixture
def target() -> TargetConfig:
    return TargetConfig(
        ticker="601985.SH",
        name="中国核电",
        thesis="AI算力需要稳定基荷电力，核电是物理刚需，兼具确定性与成长性。",
        industry="电力",
    )


@pytest.fixture
def quote() -> QuoteData:
    return QuoteData(
        date=datetime(2026, 6, 4), ticker="601985.SH",
        price_close=10.0, pe_ttm=18.0, pb=2.0,
    )


@pytest.fixture
def texts():
    return MockTextProvider().fetch_texts("601985.SH", "中国核电", max_items=6)


def _pipeline(store=None, fake=None, with_provider=True):
    return ThesisPipeline(
        fake or FakeLLMClient(n_links=3, include_due_diligence=True),
        financials_provider_factory=(lambda t: MockFinancialsProvider()) if with_provider else None,
        artifact_store=store,
    )


class TestFullRun:
    def test_runs_and_persists_five_stages(self, tmp_path, target, quote, texts):
        store = ArtifactStore(base_dir=tmp_path)
        result = _pipeline(store).run(
            target, quote=quote, texts=texts, audit_date=datetime(2026, 6, 4)
        )
        assert isinstance(result, PipelineResult)
        assert result.used_pipeline is True
        assert result.artifact_dir is not None

        stages = store.list_stages("601985.SH", datetime(2026, 6, 4))
        names = [p.name for p in stages]
        assert names == [
            "S1_refined_thesis.json",
            "S2_logic_chain.json",
            "S3_proxy_mapping.json",
            "S4_evidence.json",
            "S5_thesis_projection.json",
        ]
        # 证据链覆盖每个 link
        assert len(result.evidence) == 3
        assert result.projection.validate() is True
        # S5 产物可作为 ThesisProjection 读回
        loaded = store.load_stage(
            "601985.SH", datetime(2026, 6, 4), "thesis_projection",
            model_cls=ThesisProjection, index=5,
        )
        assert loaded.validate() is True

    def test_quantitative_link_uses_real_financial_data(self, target, quote, texts):
        result = _pipeline().run(target, quote=quote, texts=texts)
        # link 0 在 FakeLLMClient 中被标为 quantitative → 财报引擎证据，data 含真实计算指标
        q_ev = result.projection.evidence_chain[0]
        assert "revenue_cagr" in q_ev.data
        assert q_ev.data["revenue_cagr"] is not None  # 来自 MockFinancialsProvider

    def test_quantitative_judgment_receives_condition_and_metrics(
        self, target, quote, texts
    ):
        """缺口①：定量判断的 LLM 输入必须含 statement / condition / 引擎指标摘要"""
        fake = FakeLLMClient(n_links=3, include_due_diligence=True)
        _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        assert "get_quant_evidence_interpretation" in fake.calls
        kwargs = fake.last_quant_kwargs
        assert kwargs["statement"] == "环节1：影响命题的关键因素 1"
        assert kwargs["condition"] == "条件1 需成立"
        # 指标摘要来自引擎真实计算值（MockFinancialsProvider）
        assert "营收 CAGR" in kwargs["metrics_summary"]
        assert "forward PE" in kwargs["metrics_summary"]

    def test_quantitative_data_only_contains_engine_values(self, target, quote, texts):
        """缺口①：Evidence.data 只放引擎计算值，LLM 的 data 字段必须被丢弃"""
        fake = FakeLLMClient(n_links=3)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        q_ev = result.projection.evidence_chain[0]
        assert "llm_injected" not in q_ev.data  # fake 注入的字段被丢弃
        assert "revenue_cagr" in q_ev.data  # 引擎计算值保留
        # finding / supports / confidence 来自 LLM 判断
        assert q_ev.finding == "引擎指标显示「条件1 需成立」基本满足。"
        assert q_ev.supports is True
        assert q_ev.confidence == "中"

    def test_quantitative_llm_failure_falls_back_to_heuristic(
        self, target, quote, texts
    ):
        """缺口①：LLM 判断失败 → 回退引擎启发式 + needs_due_diligence=True"""
        fake = FakeLLMClient(fail_stage="get_quant_evidence_interpretation", n_links=3)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        assert result.used_pipeline is True  # 单环节失败不应整体回退
        q_ev = result.projection.evidence_chain[0]
        assert q_ev.needs_due_diligence is True
        assert "revenue_cagr" in q_ev.data  # 引擎值仍在
        # 回退环节进入尽调队列
        assert any(item["index"] == 0 for item in result.due_diligence_queue)

    def test_quantitative_irrelevant_metrics_marked_due_diligence(
        self, target, quote, texts
    ):
        """缺口①：LLM 判断指标与条件无关 → 转尽调而非强行给 supports"""
        fake = FakeLLMClient(n_links=3, quant_irrelevant=True)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        q_ev = result.projection.evidence_chain[0]
        assert q_ev.needs_due_diligence is True
        assert q_ev.supports is False
        assert q_ev.confidence == "低"
        assert any(item["index"] == 0 for item in result.due_diligence_queue)

    def test_due_diligence_link_queued_without_fabrication(self, target, quote, texts):
        result = _pipeline().run(target, quote=quote, texts=texts)
        assert len(result.due_diligence_queue) >= 1
        # link 2 = due_diligence
        dd_ev = result.projection.evidence_chain[2]
        assert dd_ev.needs_due_diligence is True
        assert dd_ev.supports is False
        assert dd_ev.data == {}  # 未编造任何数字

    def test_runs_without_artifact_store(self, target, quote, texts):
        result = _pipeline(store=None).run(target, quote=quote, texts=texts)
        assert result.used_pipeline is True
        assert result.artifact_dir is None


class TestSpinePreserved:
    def test_gap_equals_our_minus_implied(self, target, quote, texts):
        fake = FakeLLMClient(our_growth=18.0, implied_growth=8.0, n_links=3)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        pr = result.to_projection_result()
        assert isinstance(pr, ThesisProjectionResult)
        assert pr.our_growth == 18.0

        consensus = ConsensusResult(
            sentiment_score=35, sentiment_label="悲观", implied_growth=8.0,
            key_narrative="n", key_worry="w", key_hope="h",
        )
        gap_calc = GapCalculator()
        audit = gap_calc.compute_audit_result(
            ticker=target.ticker, name=target.name, price=quote.price_close,
            pe_ttm=quote.pe_ttm, consensus=consensus, thesis_projection=pr,
        )
        # 脊柱不变：gap = our_growth − implied_growth
        assert audit.gap == pytest.approx(18.0 - 8.0)
        assert audit.our_growth == 18.0
        assert audit.implied_growth == 8.0


class TestWeightedSynthesis:
    def test_synthesis_receives_link_weights(self, target, quote, texts):
        """缺口②：S5 的 evidence_items 必须带 S2 的 weight"""
        fake = FakeLLMClient(n_links=3)
        _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        items = fake.last_synthesis_items
        assert items is not None and len(items) == 3
        assert all("weight" in it for it in items)
        assert items[0]["weight"] == pytest.approx(0.33)

    def test_weighted_support_formula(self):
        """weighted_support = Σ(weight × supports × 置信系数)，高/中/低=1.0/0.6/0.3"""
        chain = LogicChain(links=[
            LogicChainLink(statement="A", weight=0.5, condition="a",
                           evidence=Evidence(finding="支持", supports=True, confidence="高")),
            LogicChainLink(statement="B", weight=0.3, condition="b",
                           evidence=Evidence(finding="支持", supports=True, confidence="低")),
            LogicChainLink(statement="C", weight=0.2, condition="c",
                           evidence=Evidence(finding="不支持", supports=False, confidence="高")),
        ])
        # 0.5×1.0 + 0.3×0.3 + 0(不支持) = 0.59
        assert ThesisPipeline.weighted_support(chain) == pytest.approx(0.59)

    def test_weighted_support_zero_without_evidence(self):
        chain = LogicChain(
            links=[LogicChainLink(statement="A", weight=0.5, condition="a")]
        )
        assert ThesisPipeline.weighted_support(chain) == 0.0

    def test_pipeline_sets_and_persists_weighted_support(
        self, tmp_path, target, quote, texts
    ):
        store = ArtifactStore(base_dir=tmp_path)
        result = _pipeline(store=store).run(
            target, quote=quote, texts=texts, audit_date=datetime(2026, 6, 11)
        )
        # link0 定量: 支持/中(0.6)、link1 定性: 支持/中(0.6)、link2 尽调: 不支持
        expected = 0.33 * 0.6 + 0.33 * 0.6
        assert result.projection.weighted_support == pytest.approx(expected, abs=1e-4)
        # 写进 S5 阶段产物且可读回
        loaded = store.load_stage(
            "601985.SH", datetime(2026, 6, 11), "thesis_projection",
            model_cls=ThesisProjection, index=5,
        )
        assert loaded.weighted_support == pytest.approx(expected, abs=1e-4)


class TestFallback:
    def test_fallback_to_single_shot_on_stage_failure(self, target, quote, texts):
        fake = FakeLLMClient(fail_stage="get_logic_chain")
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        assert result.used_pipeline is False
        assert result.evidence == []
        assert result.due_diligence_queue == []
        assert result.projection.validate() is True
        # 确实走了单次投影回退
        assert "get_thesis_projection" in fake.calls
        assert "get_proxy_mapping" not in fake.calls

    def test_no_provider_marks_quantitative_due_diligence(self, target, quote, texts):
        result = _pipeline(with_provider=False).run(target, quote=quote, texts=texts)
        # 无财报 provider → 定量环节(link0)也转尽调，且不编造数据
        q_ev = result.projection.evidence_chain[0]
        assert q_ev.needs_due_diligence is True
        assert q_ev.data == {}
