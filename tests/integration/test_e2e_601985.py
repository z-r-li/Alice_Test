"""
端到端：601985.SH（P1 完成判据）

离线 e2e（CI 默认运行）：FakeLLMClient + MockTextProvider + MockFinancialsProvider +
桩行情，跑通 AliceTestPipeline.run() 全链路（摄入 → 共识 → S1–S5 流水线 → Gap → AuditResult
→ CSV + 阶段产物），验证带完整证据链的认知差结论、脊柱不变、CSV 向后兼容。

里程碑 e2e（@integration，需 DEEPSEEK_API_KEY + 联网）：真实 DeepSeek + 真实 AkShare 财报
+ mock 文本，对应用户选定的「Real DeepSeek + AkShare」验收方式。
"""
import csv as _csv
import os
from datetime import datetime

import pytest

from src.config import load_config_from_dict
from src.data_ingestion.models import QuoteData
from src.data_ingestion.text import TextProviderFactory
from src.llm.models import ThesisProjection
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


def test_e2e_601985_offline(monkeypatch, tmp_path):
    """全链路离线 e2e：产出带证据链的认知差结论 + CSV + 五阶段产物。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from src.main import AliceTestPipeline

    TextProviderFactory.reset()
    monkeypatch.setattr(
        AliceTestPipeline, "_create_llm_client",
        lambda self: FakeLLMClient(our_growth=25.0, implied_growth=8.0, n_links=3),
    )

    csv_path = tmp_path / "audit_report.csv"
    artifacts_dir = tmp_path / "artifacts"
    config = load_config_from_dict({
        "data_sources": {"crawler": {"use_mock": True}},
        "financial_analysis": {"use_mock": True},
        "output": {"path": str(csv_path), "artifacts_dir": str(artifacts_dir)},
        "targets": [
            {"ticker": "601985.SH", "name": "中国核电",
             "thesis": "AI算力需要稳定基荷电力，核电是物理刚需，兼具确定性与成长性。",
             "industry": "电力"}
        ],
    })
    pipeline = AliceTestPipeline(config=config, output_path=csv_path)
    monkeypatch.setattr(pipeline, "_select_quotes_provider", lambda t: _FakeQuotesProvider())

    results = pipeline.run()

    # 认知差结论（脊柱不变）
    assert len(results) == 1
    r = results[0]
    assert r.ticker == "601985.SH"
    assert r.our_growth == 25.0 and r.implied_growth == 8.0
    assert r.gap == pytest.approx(25.0 - 8.0)
    assert r.signal.value in ("OPPORTUNITY", "OVERHEATED", "WAIT")
    assert r.artifact_dir is not None
    assert "证据链" in (r.evidence_summary or "")

    # CSV：原始 14 列 + 至少一行数据（向后兼容）
    assert csv_path.exists()
    with open(csv_path, encoding="utf-8") as f:
        rows = list(_csv.reader(f))
    assert rows[0] == CSVReportWriter.CSV_COLUMNS
    assert len(rows[0]) == 14
    assert len(rows) >= 2

    # 五阶段产物 + 完整证据链
    store = ArtifactStore(str(artifacts_dir))
    stages = store.list_stages("601985.SH", r.date)
    assert [p.name for p in stages] == [
        "S1_refined_thesis.json", "S2_logic_chain.json", "S3_proxy_mapping.json",
        "S4_evidence.json", "S5_thesis_projection.json",
    ]
    proj = store.load_stage(
        "601985.SH", r.date, "thesis_projection",
        model_cls=ThesisProjection, index=5,
    )
    assert proj.validate() is True
    assert len(proj.evidence_chain) == 3  # 每个 link 一条证据
    # 定量环节用真实(mock)财报数据，无 proxy 环节进尽调（不编造）
    assert "revenue_cagr" in proj.evidence_chain[0].data
    assert any(e.needs_due_diligence for e in proj.evidence_chain)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="里程碑实测需 DEEPSEEK_API_KEY + 联网（真实 DeepSeek + AkShare）",
)
def test_e2e_601985_live_milestone(tmp_path):
    """里程碑：真实 DeepSeek + 真实 AkShare 财报 + mock 文本。"""
    from src.main import AliceTestPipeline

    TextProviderFactory.reset()
    csv_path = tmp_path / "audit_report.csv"
    artifacts_dir = tmp_path / "artifacts"
    config = load_config_from_dict({
        "llm_api": {"model": "deepseek-chat", "temperature": 0},
        "data_sources": {"crawler": {"use_mock": True}},  # 文本 mock（周末/节假日可取不到）
        "financial_analysis": {"use_mock": False},  # 真实 AkShare 财报
        "output": {"path": str(csv_path), "artifacts_dir": str(artifacts_dir)},
        "targets": [
            {"ticker": "601985.SH", "name": "中国核电",
             "thesis": "AI算力需要稳定基荷电力，核电是物理刚需，兼具确定性与成长性。",
             "industry": "电力"}
        ],
    })
    pipeline = AliceTestPipeline(config=config, output_path=csv_path, verbose=True)
    results = pipeline.run()

    assert len(results) == 1
    r = results[0]
    assert -50.0 <= r.our_growth <= 100.0
    assert r.gap == pytest.approx(r.our_growth - r.implied_growth)
    store = ArtifactStore(str(artifacts_dir))
    assert len(store.list_stages("601985.SH", r.date)) == 5
