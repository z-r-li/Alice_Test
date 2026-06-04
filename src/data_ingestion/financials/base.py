"""
财报数据提供者抽象基类 (S4)

镜像 quotes/ 的结构：按市场后缀路由到 AkShare/Tushare（A 股）或 yfinance（港美股）。
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod

from .models import FinancialReport, Market


class FinancialsFetchError(Exception):
    """财报数据获取失败异常"""

    def __init__(self, message: str, ticker: str | None = None):
        self.ticker = ticker
        self.message = message
        super().__init__(f"[{ticker}] {message}" if ticker else message)


def detect_market(ticker: str) -> Market:
    """按后缀判断市场（与 quotes 选择逻辑一致）"""
    t = ticker.strip().upper()
    if t.endswith((".SH", ".SZ")):
        return "a_share"
    if t.endswith(".HK"):
        return "hk"
    return "us"


def safe_float(value) -> float | None:
    """安全转换为浮点数，NaN/Inf/无效值返回 None（绝不臆造数字）"""
    if value is None:
        return None
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (ValueError, TypeError):
        return None


class FinancialsProvider(ABC):
    """财报数据提供者抽象基类"""

    @abstractmethod
    def get_financials(
        self,
        ticker: str,
        max_periods: int = 5,
        period_type: str = "annual",
    ) -> FinancialReport:
        """
        获取财务报表数据

        Args:
            ticker: 证券代码，如 "601985.SH" / "0700.HK" / "AAPL"
            max_periods: 最多返回多少个报告期（取最近的）
            period_type: "annual"（年报，默认）或 "quarterly"

        Returns:
            FinancialReport: 多期财报数据（periods 升序）

        Raises:
            FinancialsFetchError: 数据获取失败
        """
        ...

    @abstractmethod
    def is_market_supported(self, ticker: str) -> bool:
        """判断该提供者是否支持指定市场"""
        ...
