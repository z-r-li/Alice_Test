"""
A 股行情降级链单测（离线，不触网）

覆盖：FallbackQuotesProvider 的按序降级 / 全失败抛错 / 市场支持判断，
AShareYFinanceQuotesProvider 的 Yahoo 符号映射与 ticker 还原，
以及 main._select_quotes_provider 对 akshare 配置返回降级链。
"""
from datetime import datetime

import pytest

from src.data_ingestion.models import QuoteData
from src.data_ingestion.quotes import (
    AkShareQuotesProvider,
    AShareYFinanceQuotesProvider,
    DataFetchError,
    FallbackQuotesProvider,
    QuotesProvider,
    YFinanceQuotesProvider,
)


def _quote(ticker: str, price: float = 9.07) -> QuoteData:
    return QuoteData(
        date=datetime(2026, 6, 9), ticker=ticker,
        price_close=price, pe_ttm=22.7, pb=1.55,
    )


class _OKProvider(QuotesProvider):
    def __init__(self, price: float = 9.07):
        self.price = price
        self.calls = 0

    def get_quote(self, ticker, date=None):
        self.calls += 1
        return _quote(ticker, self.price)

    def get_historical_quotes(self, ticker, start_date, end_date):
        return [_quote(ticker, self.price)]

    def is_market_supported(self, ticker):
        return True


class _FailProvider(QuotesProvider):
    def __init__(self):
        self.calls = 0

    def get_quote(self, ticker, date=None):
        self.calls += 1
        raise DataFetchError("Connection aborted", ticker)

    def get_historical_quotes(self, ticker, start_date, end_date):
        self.calls += 1
        raise DataFetchError("Connection aborted", ticker)

    def is_market_supported(self, ticker):
        return ticker.endswith(".SH")


class TestFallbackQuotesProvider:
    def test_primary_success_no_fallback(self):
        primary, backup = _OKProvider(price=8.88), _OKProvider(price=9.99)
        quote = FallbackQuotesProvider(primary, backup).get_quote("601985.SH")
        assert quote.price_close == 8.88
        assert primary.calls == 1 and backup.calls == 0

    def test_falls_back_on_primary_failure(self):
        primary, backup = _FailProvider(), _OKProvider()
        quote = FallbackQuotesProvider(primary, backup).get_quote("601985.SH")
        assert quote.price_close == 9.07
        assert primary.calls == 1 and backup.calls == 1

    def test_all_fail_raises_data_fetch_error(self):
        with pytest.raises(DataFetchError):
            FallbackQuotesProvider(_FailProvider(), _FailProvider()).get_quote(
                "601985.SH"
            )

    def test_historical_falls_back(self):
        quotes = FallbackQuotesProvider(
            _FailProvider(), _OKProvider()
        ).get_historical_quotes(
            "601985.SH", datetime(2026, 6, 1), datetime(2026, 6, 9)
        )
        assert len(quotes) == 1

    def test_requires_at_least_one_provider(self):
        with pytest.raises(ValueError):
            FallbackQuotesProvider()

    def test_market_supported_is_any(self):
        chain = FallbackQuotesProvider(_FailProvider(), _FailProvider())
        assert chain.is_market_supported("601985.SH") is True
        assert chain.is_market_supported("AAPL") is False


class TestAShareYFinanceQuotesProvider:
    def test_to_yahoo_mapping(self):
        to_yahoo = AShareYFinanceQuotesProvider._to_yahoo
        assert to_yahoo("601985.SH") == "601985.SS"
        assert to_yahoo("000001.SZ") == "000001.SZ"

    def test_market_supported(self):
        p = AShareYFinanceQuotesProvider()
        assert p.is_market_supported("601985.SH") is True
        assert p.is_market_supported("000001.SZ") is True
        assert p.is_market_supported("0700.HK") is False

    def test_get_quote_converts_symbol_and_restores_ticker(self, monkeypatch):
        seen = {}

        def fake_get_quote(self, ticker, date=None):
            seen["symbol"] = ticker
            return _quote(ticker)

        monkeypatch.setattr(YFinanceQuotesProvider, "get_quote", fake_get_quote)
        quote = AShareYFinanceQuotesProvider().get_quote("601985.SH")
        assert seen["symbol"] == "601985.SS"  # 发往 Yahoo 的是镜像符号
        assert quote.ticker == "601985.SH"  # 返回值还原原始 A 股代码

    def test_historical_restores_ticker(self, monkeypatch):
        def fake_hist(self, ticker, start_date, end_date):
            return [_quote(ticker)]

        monkeypatch.setattr(
            YFinanceQuotesProvider, "get_historical_quotes", fake_hist
        )
        quotes = AShareYFinanceQuotesProvider().get_historical_quotes(
            "601985.SH", datetime(2026, 6, 1), datetime(2026, 6, 9)
        )
        assert quotes[0].ticker == "601985.SH"


class TestMainSelectsFallbackChain:
    def test_akshare_config_returns_fallback_chain(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        from src.config import load_config_from_dict
        from src.main import AliceTestPipeline

        config = load_config_from_dict({
            "data_sources": {
                "a_shares": {"provider": "akshare"},
                "crawler": {"use_mock": True},
            },
            "financial_analysis": {"use_mock": True},
            "targets": [{
                "ticker": "601985.SH", "name": "中国核电",
                "thesis": "测试", "industry": "电力",
            }],
        })
        pipeline = AliceTestPipeline(config=config, output_path="audit.csv")
        provider = pipeline._select_quotes_provider("601985.SH")
        assert isinstance(provider, FallbackQuotesProvider)
        inner = provider._providers
        assert isinstance(inner[0], AkShareQuotesProvider)
        assert isinstance(inner[1], AShareYFinanceQuotesProvider)

    def test_quote_placeholder_is_constructible(self):
        # 行情全失败时 main 的占位 QuoteData(price_close=0.0) 必须可构造
        # （此前 gt=0 约束使降级路径必然崩溃）
        q = QuoteData(
            date=datetime(2026, 6, 9), ticker="601985.SH",
            price_close=0.0, pe_ttm=None, pb=None,
        )
        assert q.price_close == 0.0
