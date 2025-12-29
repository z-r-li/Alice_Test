"""
文本数据提供者抽象基类
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Literal

from ..models import TextItem
from .models import TextSourceType


class TextProvider(ABC):
    """文本数据提供者抽象基类"""

    @abstractmethod
    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        获取指定标的的相关文本数据

        Args:
            ticker: 证券代码
            name: 标的名称（用于搜索）
            lookback_hours: 回溯时间窗口（小时），默认 48 小时
            max_items: 最大返回条数，默认 10 条
            source_types: 可选的数据源类型过滤列表，为 None 时返回所有类型

        Returns:
            list[TextItem]: 文本数据列表，按相关性/时间排序
        """
        ...

    @abstractmethod
    def get_source_name(self) -> str:
        """
        获取数据源名称

        Returns:
            str: 如 "中信证券"、"东方财富" 等
        """
        ...

    @abstractmethod
    def supports_market(self, ticker: str) -> bool:
        """
        判断该 Provider 是否支持指定市场的 ticker

        Args:
            ticker: 证券代码，如 "601985.SH"、"0700.HK"、"AAPL"

        Returns:
            bool: 是否支持该市场
        """
        ...

    @abstractmethod
    def get_supported_source_types(self) -> list[TextSourceType]:
        """
        返回该 Provider 支持的所有数据源类型

        Returns:
            list[TextSourceType]: 支持的数据源类型列表
        """
        ...

    def _get_time_window(self, lookback_hours: int) -> tuple[datetime, datetime]:
        """
        计算时间窗口

        Args:
            lookback_hours: 回溯小时数

        Returns:
            tuple[datetime, datetime]: (start_time, end_time)
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=lookback_hours)
        return start_time, end_time

    @staticmethod
    def extract_symbol(ticker: str) -> str:
        """
        从 ticker 中提取纯代码（去除市场后缀）

        Args:
            ticker: 证券代码，如 "601985.SH"、"000001.SZ"、"0700.HK"、"AAPL"

        Returns:
            str: 纯代码部分

        Examples:
            >>> TextProvider.extract_symbol("601985.SH")
            '601985'
            >>> TextProvider.extract_symbol("000001.SZ")
            '000001'
            >>> TextProvider.extract_symbol("0700.HK")
            '0700'
            >>> TextProvider.extract_symbol("AAPL")
            'AAPL'
        """
        if "." in ticker:
            return ticker.split(".")[0]
        return ticker

    @staticmethod
    def detect_market(ticker: str) -> Literal["a_share", "hk", "us"]:
        """
        根据 ticker 后缀判断市场类型

        Args:
            ticker: 证券代码，如 "601985.SH"、"000001.SZ"、"0700.HK"、"AAPL"

        Returns:
            Literal["a_share", "hk", "us"]: 市场类型
                - "a_share": A 股（.SH 或 .SZ 后缀）
                - "hk": 港股（.HK 后缀）
                - "us": 美股（无后缀或其他）

        Examples:
            >>> TextProvider.detect_market("601985.SH")
            'a_share'
            >>> TextProvider.detect_market("000001.SZ")
            'a_share'
            >>> TextProvider.detect_market("0700.HK")
            'hk'
            >>> TextProvider.detect_market("AAPL")
            'us'
        """
        ticker_upper = ticker.upper()
        if ticker_upper.endswith(".SH") or ticker_upper.endswith(".SZ"):
            return "a_share"
        elif ticker_upper.endswith(".HK"):
            return "hk"
        else:
            return "us"
