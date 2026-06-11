"""
A 股行情降级链

东财行情接口（stock_zh_a_hist 等）在部分网络环境不可达（连接被远端重置），
而 Yahoo Finance 的 A 股镜像（601985.SH → 601985.SS）在同环境可用且带
PE/PB/市值。本模块提供：

- AShareYFinanceQuotesProvider：A 股代码映射到 Yahoo 镜像的行情源；
- FallbackQuotesProvider：按序尝试多个行情源，主源失败自动降级。

两者都是真实数据源，不涉及 mock；降级发生时记 WARNING 便于审计。
"""
from __future__ import annotations

import logging
from datetime import datetime

from .base import DataFetchError, QuotesProvider
from .yfinance_client import YFinanceQuotesProvider
from ..models import QuoteData

logger = logging.getLogger("alice_test")


class AShareYFinanceQuotesProvider(YFinanceQuotesProvider):
    """
    A 股行情的 Yahoo Finance 镜像源

    代码映射：601985.SH → 601985.SS；000001.SZ → 000001.SZ（Yahoo 同后缀）。
    返回的 QuoteData.ticker 保持原始 A 股格式，下游无感知。
    """

    SUPPORTED_SUFFIXES = (".SH", ".SZ")

    def is_market_supported(self, ticker: str) -> bool:
        """接受 A 股代码及其 Yahoo 镜像后缀（内部转换后复用父类逻辑）"""
        return ticker.upper().endswith((".SH", ".SZ", ".SS"))

    @staticmethod
    def _to_yahoo(ticker: str) -> str:
        """A 股代码 → Yahoo 符号（.SH → .SS；.SZ 不变）"""
        t = ticker.strip().upper()
        if t.endswith(".SH"):
            return t[: -len(".SH")] + ".SS"
        return t

    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        original = ticker.strip().upper()
        quote = super().get_quote(self._to_yahoo(original), date)
        return quote.model_copy(update={"ticker": original})

    def get_historical_quotes(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[QuoteData]:
        original = ticker.strip().upper()
        quotes = super().get_historical_quotes(
            self._to_yahoo(original), start_date, end_date
        )
        return [q.model_copy(update={"ticker": original}) for q in quotes]


class FallbackQuotesProvider(QuotesProvider):
    """
    行情源降级链：按序尝试，前者失败自动转后者

    所有源都失败时抛 DataFetchError（沿用 main 的 data_error 降级路径）。
    """

    def __init__(self, *providers: QuotesProvider):
        if not providers:
            raise ValueError("FallbackQuotesProvider 需要至少一个行情源")
        self._providers = providers

    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        last_exc: Exception | None = None
        for i, provider in enumerate(self._providers):
            name = type(provider).__name__
            try:
                quote = provider.get_quote(ticker, date)
                if i > 0:
                    logger.warning(f"[{ticker}] 行情主源失败，已由降级源 {name} 提供")
                return quote
            except Exception as e:
                last_exc = e
                logger.warning(f"[{ticker}] 行情源 {name} 失败: {e}")
        raise DataFetchError(f"所有行情源均失败: {last_exc}", ticker) from last_exc

    def get_historical_quotes(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[QuoteData]:
        last_exc: Exception | None = None
        for i, provider in enumerate(self._providers):
            name = type(provider).__name__
            try:
                quotes = provider.get_historical_quotes(ticker, start_date, end_date)
                if i > 0:
                    logger.warning(f"[{ticker}] 历史行情主源失败，已由降级源 {name} 提供")
                return quotes
            except Exception as e:
                last_exc = e
                logger.warning(f"[{ticker}] 历史行情源 {name} 失败: {e}")
        raise DataFetchError(f"所有行情源均失败: {last_exc}", ticker) from last_exc

    def is_market_supported(self, ticker: str) -> bool:
        return any(p.is_market_supported(ticker) for p in self._providers)
