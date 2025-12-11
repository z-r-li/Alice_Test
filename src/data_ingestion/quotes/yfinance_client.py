"""
yfinance 行情数据提供者 - 港股/美股市场
"""
from datetime import datetime

from .base import QuotesProvider
from ..models import QuoteData


class YFinanceQuotesProvider(QuotesProvider):
    """yfinance 港美股行情数据提供者"""

    def __init__(self):
        """初始化 yfinance 客户端"""
        # yfinance 无需 API Token
        pass

    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        """
        获取港/美股标的行情数据

        Args:
            ticker: 港股如 "0700.HK"，美股如 "AAPL"
            date: 查询日期

        Returns:
            QuoteData: 行情数据
        """
        # TODO: 调用 yfinance.Ticker(ticker).history()
        raise NotImplementedError

    def get_historical_quotes(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[QuoteData]:
        """获取港/美股历史行情"""
        raise NotImplementedError

    def is_market_supported(self, ticker: str) -> bool:
        """判断是否为港股/美股代码"""
        # 港股: .HK 后缀，美股: 无后缀或其他
        return ticker.endswith(".HK") or not ticker.endswith((".SH", ".SZ"))
