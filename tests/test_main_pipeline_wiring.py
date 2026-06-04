"""
main.py 多阶段流水线接线测试（离线）

用 FakeLLMClient + mock 文本/财报 + 桩行情，验证 AliceTestPipeline 默认走 ThesisPipeline、
产出带 artifact_dir / evidence_summary 的 AuditResult、脊柱 gap 不变、阶段产物落盘，
且原 CSV 14 列不受新字段影响。对应改进计划 P1 Step 8。
"""
from datetime import datetime

import pytest

from src.config import load_config_from_dict
from src.data_ingestion.models import QuoteData
from src.data_ingestion.text import TextProviderFactory
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


def _make_pipeline(monkeypatch, tmp_path, *, pipeline_enabled=True):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from src.main import AliceTestPipeline

    TextProviderFactory.reset()
    # 用假 LLM 替换真实 DeepSeek 客户端（离线、确定性）
    monkeypatch.setattr(
        AliceTestPipeline,
        "_create_llm_client",
        lambda self: FakeLLMClient(our_growth=18.0, implied_growth=8.0, n_links=3),
    )

    config = load_config_from_dict({
        "data_sources": {"crawler": {"use_mock": True}},
        "financial_analysis": {"use_mock": True},
        "pipeline": {"enabled": pipeline_enabled},
        "output": {
            "path": str(tmp_path / "out.csv"),
            "artifacts_dir": str(tmp_path / "artifacts"),
        },
        "targets": [
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

    def test_pipeline_disabled_falls_back_to_projector(self, monkeypatch, tmp_path):
        pipeline, config = _make_pipeline(monkeypatch, tmp_path, pipeline_enabled=False)
        assert pipeline._thesis_pipeline is None
        result = pipeline._process_single_target(config.targets[0])
        # 仍产出有效结果（单次 ThesisProjector 路径）
        assert result.gap == pytest.approx(18.0 - 8.0)
        assert result.artifact_dir is None
