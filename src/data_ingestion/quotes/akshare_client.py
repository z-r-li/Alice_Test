"""
AkShare 行情数据提供者 - A股市场备选
"""
from datetime import datetime

from .base import QuotesProvider
from ..models import QuoteData


class AkShareQuotesProvider(QuotesProvider):
    """AkShare A股行情数据提供者（免费备选）"""

    def __init__(self):
        """初始化 AkShare 客户端"""
        # AkShare 无需 API Token
        pass

    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        """
        获取 A 股标的行情数据

        Args:
            ticker: A股代码
            date: 查询日期

        Returns:
            QuoteData: 行情数据
        """
        # TODO: 调用 akshare 相关接口
        raise NotImplementedError

    def get_historical_quotes(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[QuoteData]:
        """获取 A 股历史行情"""
        raise NotImplementedError

    def is_market_supported(self, ticker: str) -> bool:
        """判断是否为 A 股代码"""
        return ticker.endswith((".SH", ".SZ"))
