"""
研报爬虫 - 从配置的券商来源获取研报摘要
"""
from ..models import TextItem
from .base import TextProvider


class ResearchCrawler(TextProvider):
    """研报数据爬虫"""

    def __init__(self, providers: list[str], search_entrypoints: list[str] | None = None):
        """
        初始化研报爬虫

        Args:
            providers: 允许的研报来源列表，如 ["中信证券", "华泰证券", "Morgan Stanley"]
            search_entrypoints: 搜索入口 URL 列表
        """
        self._providers = providers
        self._search_entrypoints = search_entrypoints or []

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取研报摘要

        Args:
            ticker: 证券代码
            name: 标的名称
            lookback_hours: 时间窗口
            max_items: 最大条数

        Returns:
            list[TextItem]: 研报摘要列表
        """
        # TODO: 实现研报爬取逻辑
        # 1. 根据 ticker/name 构建搜索关键词
        # 2. 在 search_entrypoints 中搜索
        # 3. 过滤只保留 providers 中的来源
        # 4. 提取摘要/投资建议/风险提示
        raise NotImplementedError

    def get_source_name(self) -> str:
        return "research"

    def _build_search_queries(self, ticker: str, name: str) -> list[str]:
        """
        构建搜索关键词

        Args:
            ticker: 证券代码
            name: 标的名称

        Returns:
            list[str]: 搜索关键词列表（中英文）
        """
        # TODO: 可选调用 LLM 生成更精准的搜索词
        raise NotImplementedError
