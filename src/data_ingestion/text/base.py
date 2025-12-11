"""
文本数据提供者抽象基类
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from ..models import TextItem


class TextProvider(ABC):
    """文本数据提供者抽象基类"""

    @abstractmethod
    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取指定标的的相关文本数据

        Args:
            ticker: 证券代码
            name: 标的名称（用于搜索）
            lookback_hours: 回溯时间窗口（小时），默认 48 小时
            max_items: 最大返回条数，默认 10 条

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
