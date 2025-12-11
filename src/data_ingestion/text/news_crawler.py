"""
新闻爬虫 - 从配置的新闻站点获取标题和摘要
"""
from ..models import TextItem
from .base import TextProvider


class NewsCrawler(TextProvider):
    """新闻数据爬虫"""

    def __init__(self, news_sites: list[str], search_entrypoints: list[str] | None = None):
        """
        初始化新闻爬虫

        Args:
            news_sites: 允许的新闻站点列表，如 ["东方财富", "彭博", "路透"]
            search_entrypoints: 搜索入口 URL 列表
        """
        self._news_sites = news_sites
        self._search_entrypoints = search_entrypoints or []

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取新闻标题和摘要

        Args:
            ticker: 证券代码
            name: 标的名称
            lookback_hours: 时间窗口
            max_items: 最大条数

        Returns:
            list[TextItem]: 新闻列表
        """
        # TODO: 实现新闻爬取逻辑
        # 1. 根据 ticker/name 构建搜索关键词
        # 2. 在 news_sites / search_entrypoints 中搜索
        # 3. 过滤非观点类内容
        # 4. 提取标题和关键内容
        raise NotImplementedError

    def get_source_name(self) -> str:
        return "news"
