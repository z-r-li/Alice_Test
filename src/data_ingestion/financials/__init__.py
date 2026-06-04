"""
财报数据摄入模块 (S4)

按市场后缀路由：A 股 → AkShare(默认) / Tushare；港美股 → yfinance。
use_mock=True 统一走 MockFinancialsProvider（离线 / 测试）。
"""
from .base import (
    FinancialsFetchError,
    FinancialsProvider,
    detect_market,
    safe_float,
)
from .models import FinancialPeriod, FinancialReport
from .akshare_client import AkShareFinancialsProvider
from .tushare_client import TushareFinancialsProvider
from .yfinance_client import YFinanceFinancialsProvider
from .mock_provider import MockFinancialsProvider


def get_financials_provider(
    ticker: str,
    *,
    use_mock: bool = False,
    a_share_provider: str = "akshare",
    tushare_token: str | None = None,
) -> FinancialsProvider:
    """按市场后缀选择财报提供者（与 quotes 选择逻辑一致）。

    Args:
        ticker: 证券代码，如 "601985.SH" / "0700.HK" / "AAPL"
        use_mock: True 时统一返回 MockFinancialsProvider（离线 / 测试）
        a_share_provider: A 股财报源，"akshare"（默认，免 token）或 "tushare"
        tushare_token: Tushare token（a_share_provider="tushare" 时需要）

    Returns:
        FinancialsProvider 实例
    """
    if use_mock:
        return MockFinancialsProvider()

    market = detect_market(ticker)
    if market == "a_share":
        if a_share_provider == "tushare":
            return TushareFinancialsProvider(api_token=tushare_token)
        return AkShareFinancialsProvider()
    return YFinanceFinancialsProvider()


__all__ = [
    "FinancialsFetchError",
    "FinancialsProvider",
    "FinancialPeriod",
    "FinancialReport",
    "AkShareFinancialsProvider",
    "TushareFinancialsProvider",
    "YFinanceFinancialsProvider",
    "MockFinancialsProvider",
    "get_financials_provider",
    "detect_market",
    "safe_float",
]
