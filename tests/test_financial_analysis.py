"""
FinancialAnalysisEngine (S4) 测试

离线：用手工构造的 FinancialReport 与 MockFinancialsProvider，覆盖趋势/CAGR、
forward PE 各 basis、PEG、支持度启发式，以及「数据缺失→需尽调、绝不编造」的护栏。
对应 P1 Step 4。
"""
import pytest

from src.data_ingestion.financials import (
    FinancialPeriod,
    FinancialReport,
    FinancialsFetchError,
    FinancialsProvider,
    MockFinancialsProvider,
)
from src.engines.financial_analysis import FinancialAnalysisEngine, FinancialMetrics
from src.llm.models import Evidence


def _growing_report(ticker="601985.SH") -> FinancialReport:
    return FinancialReport(
        ticker=ticker,
        market="a_share",
        currency="CNY",
        periods=[
            FinancialPeriod("2021-12-31", 100.0, 60.0, 10.0, 15.0),
            FinancialPeriod("2022-12-31", 110.0, 66.0, 11.0, 16.0),
            FinancialPeriod("2023-12-31", 121.0, 72.0, 12.1, 18.0),
            FinancialPeriod("2024-12-31", 133.0, 79.0, 13.3, 20.0),
        ],
    )


def _declining_report(ticker="600150.SH") -> FinancialReport:
    return FinancialReport(
        ticker=ticker,
        market="a_share",
        currency="CNY",
        periods=[
            FinancialPeriod("2022-12-31", 200.0, 120.0, 20.0, 30.0),
            FinancialPeriod("2023-12-31", 180.0, 120.0, 12.0, 10.0),
            FinancialPeriod("2024-12-31", 150.0, 110.0, 5.0, -5.0),
        ],
    )


class _RaisingProvider(FinancialsProvider):
    def get_financials(self, ticker, max_periods=5, period_type="annual"):
        raise FinancialsFetchError("network down", ticker)

    def is_market_supported(self, ticker):
        return True


class TestProxyCapabilityWhitelist:
    """P0-1：引擎能力边界白名单 —— 哪些 proxy 才允许走定量证据路径。"""

    @pytest.mark.parametrize(
        "spec",
        [
            "财报：营收/毛利/现金流趋势 + forward PE",
            "营收 CAGR 与净利率趋势",
            "毛利率是否持续提升",
            "trailing PE 与 PEG 估值",
            "经营性现金流是否为正",
            "revenue CAGR and net margin",
        ],
    )
    def test_in_whitelist_specs_are_computable(self, spec):
        assert FinancialAnalysisEngine.is_proxy_computable(spec) is True

    @pytest.mark.parametrize(
        "spec",
        [
            "IEA 全球 AI 用电量增速",
            "Clarksons 新船在手订单量",
            "克拉克森船价指数",
            "Wind 行业 ROE 对比",
            "分部收入拆分（云业务）",
            "年度回购金额",
            "重置成本法估值",
            "产能利用率与开工率",
            "板块溢价率",
            "装机容量同比",
            "市场份额 / 渗透率",
            # 夹带财务名词但跨公司口径（行业/分部）仍判越界
            "净利率高于行业平均",
            "分部营收占比",
        ],
    )
    def test_out_of_whitelist_specs_not_computable(self, spec):
        assert FinancialAnalysisEngine.is_proxy_computable(spec) is False

    def test_empty_spec_not_computable(self):
        assert FinancialAnalysisEngine.is_proxy_computable(None) is False
        assert FinancialAnalysisEngine.is_proxy_computable("  ") is False

    def test_ascii_token_uses_word_boundary(self):
        """'pe' 不应误命中 'competitive landscape' 这类无关英文。"""
        assert FinancialAnalysisEngine.is_proxy_computable(
            "competitive landscape positioning"
        ) is False


class TestAnalyzeReport:
    def test_growth_trends_and_cagr(self):
        engine = FinancialAnalysisEngine()
        m = engine.analyze_report(_growing_report(), trailing_pe=15.0)
        assert m.status == "ok"
        assert m.revenue_cagr == pytest.approx(10.0, abs=0.3)
        assert m.revenue_trend == "improving"
        assert m.gross_margin_trend == "stable"
        assert m.net_margin_trend == "stable"
        assert m.ocf_latest_positive is True
        assert m.revenue_yoy == pytest.approx((133 / 121 - 1) * 100, abs=0.1)

    def test_forward_pe_basis_provider(self):
        report = _growing_report()
        report.forward_pe = 12.0
        m = FinancialAnalysisEngine().analyze_report(report, trailing_pe=15.0)
        assert m.forward_pe == 12.0
        assert m.forward_pe_basis == "provider"

    def test_forward_pe_derived_from_growth(self):
        m = FinancialAnalysisEngine().analyze_report(
            _growing_report(), trailing_pe=15.0, expected_growth_pct=20.0
        )
        assert m.forward_pe == pytest.approx(15.0 / 1.2, abs=0.01)
        assert m.forward_pe_basis == "derived_from_growth"

    def test_forward_pe_derived_from_history(self):
        m = FinancialAnalysisEngine().analyze_report(_growing_report(), trailing_pe=15.0)
        assert m.forward_pe_basis == "derived_from_history"
        assert m.forward_pe is not None and m.forward_pe < 15.0
        # PEG = trailing_pe / earnings_cagr%
        assert m.peg_ratio == pytest.approx(15.0 / m.earnings_cagr, abs=0.05)

    def test_forward_pe_unavailable_without_trailing_pe(self):
        m = FinancialAnalysisEngine().analyze_report(_growing_report(), trailing_pe=None)
        assert m.forward_pe is None
        assert m.forward_pe_basis == "unavailable"
        assert any("尽调" in n for n in m.notes)


class TestBuildEvidence:
    def test_growing_company_supports_with_real_data(self):
        engine = FinancialAnalysisEngine()
        m = engine.analyze_report(_growing_report(), trailing_pe=15.0)
        ev = engine.build_evidence(m, condition="盈利能力可持续")
        assert isinstance(ev, Evidence)
        assert ev.supports is True
        assert ev.confidence == "高"
        assert ev.validate() is True
        # data 仅含真实计算值
        assert ev.data["revenue_cagr"] == pytest.approx(10.0, abs=0.3)
        assert ev.needs_due_diligence is False

    def test_declining_company_does_not_support(self):
        engine = FinancialAnalysisEngine()
        m = engine.analyze_report(_declining_report(), trailing_pe=15.0)
        ev = engine.build_evidence(m)
        assert ev.supports is False

    def test_missing_data_marks_due_diligence_no_fabrication(self):
        """空报表 → 需尽调；不臆造数字"""
        engine = FinancialAnalysisEngine()
        empty = FinancialReport(ticker="X.SH", market="a_share", periods=[], status="data_error")
        m = engine.analyze_report(empty)
        ev = engine.build_evidence(m)
        assert ev.needs_due_diligence is True
        assert ev.supports is False
        assert ev.confidence == "低"
        assert "尽调" in ev.finding
        # 关键数字保持 None（未被编造）
        assert ev.data["revenue_latest"] is None
        assert ev.data["forward_pe"] is None


class TestMetricsSummary:
    def test_summary_contains_engine_values_only(self):
        engine = FinancialAnalysisEngine()
        m = engine.analyze_report(_growing_report(), trailing_pe=15.0)
        summary = engine.metrics_summary(m)
        assert f"营收 CAGR: {m.revenue_cagr:.2f}%" in summary
        assert f"forward PE: {m.forward_pe:.2f}" in summary
        assert "经营现金流为正: 是" in summary

    def test_summary_marks_missing_values_not_fabricated(self):
        engine = FinancialAnalysisEngine()
        m = FinancialMetrics(ticker="X.SH")  # 全空指标
        summary = engine.metrics_summary(m)
        assert "无数据" in summary
        # 不应出现任何编造的数字行
        assert "CAGR: 0.00" not in summary


class TestAnalyzeTicker:
    def test_with_mock_provider(self):
        engine = FinancialAnalysisEngine(MockFinancialsProvider())
        m = engine.analyze_ticker("601985.SH", trailing_pe=18.0)
        assert m.status in ("ok", "partial")
        assert m.periods_used >= 3
        assert m.revenue_cagr is not None

    def test_fetch_failure_returns_data_error_not_raise(self):
        engine = FinancialAnalysisEngine(_RaisingProvider())
        m = engine.analyze_ticker("ANY.SH", trailing_pe=10.0)
        assert m.status == "data_error"
        assert any("尽调" in n for n in m.notes)
        # 仍能安全产出 Evidence
        ev = engine.build_evidence(m)
        assert ev.needs_due_diligence is True
