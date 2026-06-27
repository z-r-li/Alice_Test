"""
main.py 多阶段流水线接线测试（离线）

用 FakeLLMClient + mock 文本/财报 + 桩行情，验证 AliceTestPipeline 默认走 ThesisPipeline、
产出带 artifact_dir / evidence_summary 的 AuditResult、脊柱 gap 不变、阶段产物落盘，
且原 CSV 14 列不受新字段影响。对应 P1 Step 8。
"""
import math
from datetime import datetime

import pytest

from src.config import load_config_from_dict
from src.data_ingestion.models import QuoteData
from src.data_ingestion.text import TextProviderFactory
from src.engines.gap_calculator import AuditSignal
from src.llm.deepseek_client import ContentModerationError
from src.persistence import ArtifactStore, CSVReportWriter
from tests.fakes import FakeLLMClient


class _FakeQuotesProvider:
    def get_quote(self, ticker, date=None):
        return QuoteData(
            date=datetime(2026, 6, 4), ticker=ticker,
            price_close=10.0, pe_ttm=18.0, pb=2.0,
        )

    def get_historical_quotes(self, ticker, start_date, end_date):
        return []

    def is_market_supported(self, ticker):
        return True


class _FailingQuotesProvider:
    def get_quote(self, ticker, date=None):
        raise RuntimeError("all quote sources down")

    def get_historical_quotes(self, ticker, start_date, end_date):
        return []

    def is_market_supported(self, ticker):
        return True


def _make_pipeline(
    monkeypatch,
    tmp_path,
    *,
    pipeline_enabled=True,
    our_growth=18.0,
    implied_growth=8.0,
    risk_enabled=True,
    targets=None,
    fail_stage=None,
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from src.main import AliceTestPipeline

    TextProviderFactory.reset()
    # 用假 LLM 替换真实 DeepSeek 客户端（离线、确定性）
    monkeypatch.setattr(
        AliceTestPipeline,
        "_create_llm_client",
        lambda self: FakeLLMClient(
            our_growth=our_growth, implied_growth=implied_growth, n_links=3,
            fail_stage=fail_stage,
        ),
    )

    config = load_config_from_dict({
        "data_sources": {"crawler": {"use_mock": True}},
        "financial_analysis": {"use_mock": True},
        "pipeline": {"enabled": pipeline_enabled},
        "risk": {"enabled": risk_enabled},
        "output": {
            "path": str(tmp_path / "out.csv"),
            "artifacts_dir": str(tmp_path / "artifacts"),
        },
        "targets": targets if targets is not None else [
            {"ticker": "601985.SH", "name": "中国核电",
             "thesis": "AI算力需要稳定基荷电力，核电是物理刚需。", "industry": "电力"}
        ],
    })
    pipeline = AliceTestPipeline(config=config, output_path=tmp_path / "out.csv")
    # 桩行情，避免真实网络
    monkeypatch.setattr(pipeline, "_select_quotes_provider", lambda ticker: _FakeQuotesProvider())
    return pipeline, config


class TestMainPipelineWiring:
    def test_process_target_uses_pipeline_and_sets_fields(self, monkeypatch, tmp_path):
        pipeline, config = _make_pipeline(monkeypatch, tmp_path)
        target = config.targets[0]
        result = pipeline._process_single_target(target)

        # 脊柱不变
        assert result.gap == pytest.approx(18.0 - 8.0)
        assert result.our_growth == 18.0
        assert result.implied_growth == 8.0
        # P1 新字段
        assert result.artifact_dir is not None
        assert "证据链" in (result.evidence_summary or "")

        # 五阶段产物落盘
        store = ArtifactStore(str(tmp_path / "artifacts"))
        stages = store.list_stages("601985.SH", result.date)
        assert len(stages) == 5

    def test_csv_columns_unchanged_backward_compatible(self, monkeypatch, tmp_path):
        pipeline, config = _make_pipeline(monkeypatch, tmp_path)
        result = pipeline._process_single_target(config.targets[0])

        csv_path = tmp_path / "bc.csv"
        writer = CSVReportWriter(csv_path)
        writer.save(result)  # 含新字段的 AuditResult 仍能写入原 14 列

        import csv as _csv
        with open(csv_path, encoding="utf-8") as f:
            rows = list(_csv.reader(f))
        assert rows[0] == CSVReportWriter.CSV_COLUMNS
        assert len(rows[0]) == 14  # 原始列数不变

    def test_quote_failure_propagates_data_error_status(self, monkeypatch, tmp_path):
        # 行情全失败 → 占位 price_close=0.0 继续分析，但结果状态必须是 data_error，
        # 不得被统计/落盘为 ok（运行摘要计为 ✗、退出码 2）
        pipeline, config = _make_pipeline(monkeypatch, tmp_path)
        monkeypatch.setattr(
            pipeline, "_select_quotes_provider",
            lambda ticker: _FailingQuotesProvider(),
        )
        result = pipeline._process_single_target(config.targets[0])
        assert result.status == "data_error"
        assert result.price == 0.0  # 占位价格如实保留

    def test_pipeline_disabled_falls_back_to_projector(self, monkeypatch, tmp_path):
        pipeline, config = _make_pipeline(monkeypatch, tmp_path, pipeline_enabled=False)
        assert pipeline._thesis_pipeline is None
        result = pipeline._process_single_target(config.targets[0])
        # 仍产出有效结果（单次 ThesisProjector 路径）
        assert result.gap == pytest.approx(18.0 - 8.0)
        assert result.artifact_dir is None

    def test_risk_engine_backfills_opportunity_fields(self, monkeypatch, tmp_path):
        # S6 接线：OPPORTUNITY 标的（gap=25-8=17>10、sentiment=35<40、thesis_aligned）
        # 经端到端 mock 流水线后，应回填 suggested_weight + structural_exit。
        pipeline, config = _make_pipeline(
            monkeypatch, tmp_path, our_growth=25.0, implied_growth=8.0
        )
        assert pipeline._risk_engine is not None
        results = pipeline.run()

        assert len(results) == 1
        r = results[0]
        assert r.signal is AuditSignal.OPPORTUNITY
        # 组合层 sizing：单标的 → 默认 ref_weight 0.05（受软护栏/簇上限/预算约束，未触顶）
        assert r.suggested_weight == pytest.approx(0.05)
        assert r.risk_adjusted_action == "BUY"
        # 结构性退出来自 S1 RefinedThesis.kill_criteria（FakeLLMClient 固定值）
        assert r.structural_exit == ["核心政策逆转", "毛利率持续下滑"]
        # 单标的、单簇 → 无同簇相关 flag；D3 量化退出 v0.1 留空
        assert r.correlation_flags == []
        assert r.quant_exit_target is None

    def test_risk_disabled_leaves_fields_none(self, monkeypatch, tmp_path):
        # config.risk.enabled=False → 不构建引擎、不回填，风控字段保持 None（向后兼容）。
        pipeline, config = _make_pipeline(
            monkeypatch, tmp_path, our_growth=25.0, implied_growth=8.0,
            risk_enabled=False,
        )
        assert pipeline._risk_engine is None
        r = pipeline.run()[0]
        assert r.signal is AuditSignal.OPPORTUNITY  # 信号判定不受风控开关影响
        assert r.suggested_weight is None
        assert r.structural_exit is None
        assert r.risk_adjusted_action is None
        assert r.correlation_flags is None

    def test_data_error_not_sized_even_if_opportunity(self, monkeypatch, tmp_path):
        # 降级运行：行情全失败 → status=data_error，占位 price=0.0。即便信号恰为
        # OPPORTUNITY（gap/sentiment 仍按值判定），也不得拿正权重 / 给 BUY，
        # 不占用同簇与整体风险预算（否则会稀释正常标的）。
        pipeline, config = _make_pipeline(
            monkeypatch, tmp_path, our_growth=25.0, implied_growth=8.0
        )
        monkeypatch.setattr(
            pipeline, "_select_quotes_provider",
            lambda ticker: _FailingQuotesProvider(),
        )
        r = pipeline.run()[0]
        assert r.status == "data_error"
        assert r.signal is AuditSignal.OPPORTUNITY  # 信号本身不被风控否决
        assert r.suggested_weight == 0.0  # 但不给正权重
        assert r.risk_adjusted_action != "BUY"  # 不建议买入
        # 结构性退出（来自 thesis kill_criteria，与行情无关）仍可填充
        assert r.structural_exit == ["核心政策逆转", "毛利率持续下滑"]

    def test_unknown_industry_not_clustered(self, monkeypatch, tmp_path):
        # 未填 industry（TargetConfig 默认 "未知"）不应被并成一个合成簇：
        # 4 个 OPPORTUNITY × 0.05 = 0.20 > 0.15，若误当真实同簇会错误缩权到 0.0375。
        # 归一到引擎 UNKNOWN 哨兵后：各自 0.05、互不 correlation_flag。
        targets = [
            {"ticker": f"T{i}.SH", "name": f"标的{i}",
             "thesis": f"信念{i}：长期成长。"}  # 不写 industry → 默认 "未知"
            for i in range(4)
        ]
        pipeline, config = _make_pipeline(
            monkeypatch, tmp_path, our_growth=25.0, implied_growth=8.0,
            targets=targets,
        )
        results = pipeline.run()
        assert len(results) == 4
        assert all(r.signal is AuditSignal.OPPORTUNITY for r in results)
        assert all(r.suggested_weight == pytest.approx(0.05) for r in results)
        assert all(r.correlation_flags == [] for r in results)


class TestMainFailClosed:
    """PR-A fail-closed：失败 / 缺数据路径绝不产出可计算 gap，而是标记行（不进正常样本）。"""

    def test_no_texts_fail_closed(self, monkeypatch, tmp_path):
        pipeline, config = _make_pipeline(monkeypatch, tmp_path, risk_enabled=False)
        monkeypatch.setattr(pipeline, "_fetch_texts", lambda target: [])
        result = pipeline._process_single_target(config.targets[0])

        assert result.status == "data_partial"
        assert result.needs_due_diligence is True
        assert result.signal is AuditSignal.WAIT
        # 绝不产出可计算 gap：增长率 / gap 均为 NaN（非可比，不会误触发信号）
        assert math.isnan(result.gap)
        assert math.isnan(result.our_growth)
        assert math.isnan(result.implied_growth)

    def test_consensus_moderation_fail_closed(self, monkeypatch, tmp_path):
        pipeline, config = _make_pipeline(monkeypatch, tmp_path, risk_enabled=False)

        def _raise(raw_data):
            raise ContentModerationError("Content Exists Risk")

        monkeypatch.setattr(pipeline._consensus_engine, "analyze", _raise)
        result = pipeline._process_single_target(config.targets[0])

        assert result.status == "llm_error"
        assert result.needs_due_diligence is True
        assert math.isnan(result.gap)

    def test_pipeline_fallback_flagged_not_normal_sample(self, monkeypatch, tmp_path):
        # 流水线 S2 失败 → 整体回退单次投影：gap 仍算（供人工参考），但行被标 pipeline_error
        # + needs_due_diligence，不进正常 alpha/IC 样本。
        pipeline, config = _make_pipeline(
            monkeypatch, tmp_path, risk_enabled=False, fail_stage="get_logic_chain"
        )
        result = pipeline._process_single_target(config.targets[0])

        assert result.status == "pipeline_error"
        assert result.needs_due_diligence is True
        assert result.evidence_summary == "单次投影（流水线回退）"
        # 计算值保留供人工对照（脊柱 gap = our − implied）
        assert result.gap == pytest.approx(18.0 - 8.0)

    def test_fail_closed_row_excluded_from_sizing(self, monkeypatch, tmp_path):
        # 端到端：风控启用 + 无文本 → fail-closed 行不参与 sizing（不拿正权重 / 不 BUY）。
        pipeline, config = _make_pipeline(
            monkeypatch, tmp_path, our_growth=25.0, implied_growth=8.0,
        )
        monkeypatch.setattr(pipeline, "_fetch_texts", lambda target: [])
        r = pipeline.run()[0]
        assert r.status == "data_partial"
        assert r.needs_due_diligence is True
        assert r.suggested_weight == 0.0
        assert r.risk_adjusted_action != "BUY"
