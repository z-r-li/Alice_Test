"""
财报数据提供者测试

离线单元测试基于 MockFinancialsProvider；另含一个 @pytest.mark.integration 的
AkShare 实测用例（东方财富接口，对 601985.SH）。对应 P1 Step 3。
"""
import pytest

from src.data_ingestion.financials import (
    AkShareFinancialsProvider,
    FinancialPeriod,
    FinancialReport,
    MockFinancialsProvider,
    TushareFinancialsProvider,
    YFinanceFinancialsProvider,
    get_financials_provider,
)
from src.data_ingestion.financials.base import detect_market


class TestFinancialModels:
    """FinancialPeriod / FinancialReport 计算属性"""

    def test_gross_and_net_margin(self):
        p = FinancialPeriod(
            period="2024-12-31",
            revenue=100.0,
            operating_cost=60.0,
            net_income=12.0,
            operating_cashflow=20.0,
        )
        assert p.gross_margin == pytest.approx(40.0)
        assert p.net_margin == pytest.approx(12.0)

    def test_margins_none_when_data_missing(self):
        p = FinancialPeriod(period="2024-12-31", revenue=None, operating_cost=60.0)
        assert p.gross_margin is None
        assert p.net_margin is None

    def test_report_latest_and_empty(self):
        empty = FinancialReport(ticker="X", market="us")
        assert empty.is_empty() is True
        assert empty.latest is None


class TestMockFinancialsProvider:
    """离线 mock 提供者"""

    def test_a_share_report_ascending_and_no_forward_pe(self):
        report = MockFinancialsProvider().get_financials("601985.SH")
        assert report.status == "ok"
        assert report.market == "a_share"
        assert report.currency == "CNY"
        assert report.forward_pe is None
        # periods 升序（旧→新）
        periods = [p.period for p in report.periods]
        assert periods == sorted(periods)
        assert report.latest.revenue > 0

    def test_us_report_has_forward_pe(self):
        report = MockFinancialsProvider().get_financials("AAPL")
        assert report.market == "us"
        assert report.forward_pe == pytest.approx(28.0)
        assert report.peg_ratio == pytest.approx(2.5)

    def test_max_periods_slices_latest(self):
        report = MockFinancialsProvider().get_financials("601985.SH", max_periods=2)
        assert len(report.periods) == 2
        assert report.periods[-1].period == "2025-12-31"

    def test_unknown_ticker_uses_default(self):
        report = MockFinancialsProvider().get_financials("ZZZZ.SH")
        assert report.status == "ok"
        assert len(report.periods) > 0

    def test_supports_all_markets(self):
        prov = MockFinancialsProvider()
        assert prov.is_market_supported("601985.SH")
        assert prov.is_market_supported("AAPL")


class TestProviderSelection:
    """get_financials_provider 路由"""

    def test_use_mock_returns_mock(self):
        prov = get_financials_provider("601985.SH", use_mock=True)
        assert isinstance(prov, MockFinancialsProvider)

    def test_a_share_default_akshare(self):
        prov = get_financials_provider("601985.SH")
        assert isinstance(prov, AkShareFinancialsProvider)

    def test_a_share_tushare_when_selected(self):
        prov = get_financials_provider(
            "601985.SH", a_share_provider="tushare", tushare_token="x"
        )
        assert isinstance(prov, TushareFinancialsProvider)

    @pytest.mark.parametrize("ticker", ["0700.HK", "AAPL"])
    def test_hk_us_uses_yfinance(self, ticker):
        prov = get_financials_provider(ticker)
        assert isinstance(prov, YFinanceFinancialsProvider)

    def test_detect_market(self):
        assert detect_market("601985.SH") == "a_share"
        assert detect_market("000001.SZ") == "a_share"
        assert detect_market("0700.HK") == "hk"
        assert detect_market("AAPL") == "us"


@pytest.mark.integration
class TestAkShareFinancialsLive:
    """实测：东方财富财报接口（需网络）"""

    def test_fetch_601985_financials(self):
        report = AkShareFinancialsProvider().get_financials("601985.SH", max_periods=4)
        assert report.status == "ok"
        assert report.market == "a_share"
        assert len(report.periods) >= 3
        latest = report.latest
        assert latest is not None
        assert latest.revenue and latest.revenue > 0
        assert latest.net_income is not None
        # 毛利率应在合理区间
        gm = latest.gross_margin
        assert gm is not None and 0 < gm < 100
        # 年报报告期应以 12-31 结尾
        assert all(p.period.endswith("-12-31") for p in report.periods)
