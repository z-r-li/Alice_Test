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

    def test_quantitative_unrelated_engine_gap_does_not_force_due_diligence(
        self, target, texts
    ):
        """P0-3/eb5cba5：引擎的公司级缺口（无 trailing PE → forward PE 不可用）与条件无关时，
        不应覆盖 LLM 的按条件判断强制尽调；缺口信息仍如实进了 LLM 指标摘要供其裁量。"""
        quote = QuoteData(
            date=datetime(2026, 6, 11), ticker="601985.SH",
            price_close=10.0, pe_ttm=None, pb=2.0,
        )
        fake = FakeLLMClient(n_links=3)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        q_ev = result.projection.evidence_chain[0]
        assert q_ev.supports is True
        assert q_ev.needs_due_diligence is False  # 不被引擎缺口强制入队
        assert not any(item["index"] == 0 for item in result.due_diligence_queue)
        # 缺口信息仍如实进了 LLM 的指标摘要，由其按条件相关性裁量
        assert "前瞻估值数据不足" in fake.last_quant_kwargs["metrics_summary"]

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

    def test_out_of_scope_quant_proxy_downgraded_to_due_diligence(
        self, target, quote, texts
    ):
        """P0-1：S3 把越界 proxy（引擎算不出）误标 quantitative 时，代码侧兜底降级为尽调，
        不进定量证据路径（不再用无关公司财务冒充验证）。"""
        fake = FakeLLMClient(n_links=3, quant_out_of_scope=True)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        # link0 被降级：不再是 quantitative，且不应触发定量 LLM 判断
        link0 = result.logic_chain.links[0]
        assert link0.proxy_type == "due_diligence"
        assert link0.proxy_spec.startswith("[引擎不可算→转尽调]")
        assert "get_quant_evidence_interpretation" not in fake.calls
        # 证据如实转尽调、不编造数字、入队
        q_ev = result.projection.evidence_chain[0]
        assert q_ev.needs_due_diligence is True
        assert q_ev.supports is False
        assert q_ev.data == {}
        assert any(item["index"] == 0 for item in result.due_diligence_queue)

    def test_in_scope_quant_proxy_stays_quantitative(self, target, quote, texts):
        """P0-1 不回归 P0-2：白名单内的定量 proxy 仍走定量证据路径（引擎计算值 + LLM 条件判断）。"""
        fake = FakeLLMClient(n_links=3)  # link0 默认是白名单内的财报 proxy
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        link0 = result.logic_chain.links[0]
        assert link0.proxy_type == "quantitative"
        assert "get_quant_evidence_interpretation" in fake.calls
        q_ev = result.projection.evidence_chain[0]
        assert "revenue_cagr" in q_ev.data  # 引擎计算值仍在

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


class TestDueDiligenceFallback:
    """P0-3：缺数据不入尽调队列的确定性兜底（不依赖 LLM 自觉）。"""

    def test_empty_data_low_confidence_flagged(self):
        ev = Evidence(data={}, finding="信息不足，无法判断", supports=False,
                      confidence="低")
        out = ThesisPipeline._ensure_due_diligence(ev)
        assert out.needs_due_diligence is True

    def test_nonempty_data_low_confidence_not_flagged(self):
        """定量证据 data 恒非空 → 不被兜底规则塞回队列（不回归 #71/eb5cba5 的收窄）。"""
        ev = Evidence(data={"revenue_cagr": 10.0, "status": "partial"},
                      finding="营收增长，部分科目缺失", supports=True, confidence="低")
        out = ThesisPipeline._ensure_due_diligence(ev)
        assert out.needs_due_diligence is False

    def test_empty_data_mid_confidence_not_flagged(self):
        ev = Evidence(data={}, finding="基本支持", supports=True, confidence="中")
        out = ThesisPipeline._ensure_due_diligence(ev)
        assert out.needs_due_diligence is False

    def test_already_flagged_is_noop(self):
        ev = Evidence(data={}, finding="缺 proxy", supports=False, confidence="低",
                      needs_due_diligence=True)
        out = ThesisPipeline._ensure_due_diligence(ev)
        assert out.needs_due_diligence is True

    def test_qualitative_insufficient_link_auto_queued(self, target, quote, texts):
        """定性环节「信息不足」(空 data + 低置信、LLM 未给 needs_due_diligence) → 确定性入队。"""
        fake = FakeLLMClient(n_links=3, qualitative_insufficient=True)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        # link1 = qualitative，被兜底规则转尽调
        q_ev = result.projection.evidence_chain[1]
        assert q_ev.confidence == "低"
        assert q_ev.data == {}
        assert q_ev.needs_due_diligence is True
        assert any(item["index"] == 1 for item in result.due_diligence_queue)

    def test_supported_qualitative_not_queued(self, target, quote, texts):
        """正常定性环节（中置信、有 data）不被兜底误入队。"""
        fake = FakeLLMClient(n_links=3)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        q_ev = result.projection.evidence_chain[1]
        assert q_ev.needs_due_diligence is False
        assert not any(item["index"] == 1 for item in result.due_diligence_queue)


class TestS2DriverRetry:
    """#8：S2 必须产出可被引擎验证的驱动环节，否则一次有界重试，仍无则诚实标无锚。"""

    def test_no_retry_when_driver_present(self, target, quote, texts):
        """回归：本就有可算驱动的 thesis 不触发重试、不改既有产物结构（不回归 P0-1/2/4）。"""
        fake = FakeLLMClient(n_links=3)  # link0 默认白名单内可算 proxy
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        assert fake.logic_chain_calls == [False]  # 只调一次 S2，无重试
        assert result.s2_retried is False
        assert result.no_quantitative_anchor is False
        assert result.n_quantitative_drivers == 1
        assert fake.last_synthesis_no_anchor is False  # S5 未被打无锚标
        assert result.projection.no_quantitative_anchor is False
        # 既有产物结构不变：link0 仍走定量证据路径、引擎计算值在场
        assert result.logic_chain.links[0].proxy_type == "quantitative"
        assert "revenue_cagr" in result.projection.evidence_chain[0].data
        assert len(result.evidence) == 3

    def test_retry_triggered_and_succeeds_with_driver(self, target, quote, texts):
        """全外部口径 thesis → 触发重试，重试传入 enforce_driver；重试拿到驱动 → 不打无锚标。"""
        fake = FakeLLMClient(n_links=3, driver_on_retry=True)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        # 触发了一次重试，且重试调用带 enforce_driver=True
        assert fake.logic_chain_calls == [False, True]
        assert result.s2_retried is True
        # 重试后 link0 变为白名单内可算驱动 → n_quant=1，不标无锚
        assert result.n_quantitative_drivers == 1
        assert result.no_quantitative_anchor is False
        assert result.projection.no_quantitative_anchor is False
        assert fake.last_synthesis_no_anchor is False
        assert result.logic_chain.links[0].proxy_type == "quantitative"
        assert "get_quant_evidence_interpretation" in fake.calls
        assert "revenue_cagr" in result.projection.evidence_chain[0].data

    def test_retry_still_no_driver_marks_no_anchor_without_fabrication(
        self, target, quote, texts
    ):
        """重试后仍无驱动 → 打 no_quantitative_anchor，不伪造 quantitative，S5 被显式告知。"""
        fake = FakeLLMClient(n_links=3, quant_out_of_scope=True)  # 两轮都越界
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        assert fake.logic_chain_calls == [False, True]  # 触发了重试
        assert result.s2_retried is True
        assert result.n_quantitative_drivers == 0
        # 诚实标无锚（产物 + 投影）
        assert result.no_quantitative_anchor is True
        assert result.projection.no_quantitative_anchor is True
        assert "n_quant=0" in result.projection.no_anchor_reason
        # S5 被显式告知无锚（逼其说明 our_growth 无定量锚）
        assert fake.last_synthesis_no_anchor is True
        # 绝不伪造 quantitative：越界环节被降级尽调、未走定量 LLM、未编造数字
        assert result.logic_chain.links[0].proxy_type == "due_diligence"
        assert "get_quant_evidence_interpretation" not in fake.calls
        assert result.projection.evidence_chain[0].data == {}
        assert result.projection.evidence_chain[0].needs_due_diligence is True

    def test_no_anchor_does_not_corrupt_gap_spine(self, target, quote, texts):
        """无锚标记是附加元数据：不进 to_projection_result / 不污染脊柱字段。"""
        fake = FakeLLMClient(n_links=3, quant_out_of_scope=True, our_growth=0.0)
        result = _pipeline(fake=fake).run(target, quote=quote, texts=texts)
        pr = result.to_projection_result()
        assert pr.our_growth == 0.0  # 脊柱字段照常退化
        assert not hasattr(pr, "no_quantitative_anchor")  # 不泄漏进向后兼容结果

    def test_summary_surfaces_no_anchor(self):
        """#8：main 摘要（写入 evidence_summary，非 CSV 列）显式标注无定量锚。"""
        from src.main import AliceTestPipeline
        from src.llm.models import ThesisProjection

        proj = ThesisProjection(
            thesis_aligned=False, our_growth=0.0, confidence="低",
            reasoning="thesis 无引擎可验证驱动，our_growth 无定量锚，给出零增长。",
            no_quantitative_anchor=True,
        )
        pr = PipelineResult(
            projection=proj, evidence=[], due_diligence_queue=[{"index": 0}],
            used_pipeline=True, no_quantitative_anchor=True, s2_retried=True,
        )
        summary = AliceTestPipeline._summarize_evidence(pr)
        assert "无定量锚" in summary
        # 未标无锚时不污染
        pr2 = PipelineResult(projection=proj, evidence=[], used_pipeline=True)
        assert "无定量锚" not in AliceTestPipeline._summarize_evidence(pr2)


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
