"""
行情数据提供者抽象基类
"""
from abc import ABC, abstractmethod
from datetime import datetime

from ..models import QuoteData


class QuotesProvider(ABC):
    """行情数据提供者抽象基类"""

    @abstractmethod
    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        """
        获取指定标的的行情数据

        Args:
            ticker: 证券代码，如 "601985.SH"
            date: 查询日期，默认为最新交易日

        Returns:
            QuoteData: 行情数据对象

        Raises:
            DataFetchError: 数据获取失败
        """
        ...

    @abstractmethod
    def get_historical_quotes(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[QuoteData]:
        """
        获取历史行情数据

        Args:
            ticker: 证券代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            list[QuoteData]: 历史行情数据列表
        """
        ...

    @abstractmethod
    def is_market_supported(self, ticker: str) -> bool:
        """
        判断该提供者是否支持指定市场

        Args:
            ticker: 证券代码

        Returns:
            bool: 是否支持
        """
        ...
