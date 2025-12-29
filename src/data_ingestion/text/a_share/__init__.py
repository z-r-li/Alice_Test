"""
A 股文本数据采集模块

包含 A 股市场特有的文本数据获取器实现和聚合 Provider。
"""

from .irm_fetcher import IRMFetcher
from .news_fetcher import NewsFetcher
from .provider import AShareTextProvider
from .rating_fetcher import RatingFetcher
from .research_fetcher import ResearchFetcher

__all__: list[str] = [
    "AShareTextProvider",
    "IRMFetcher",
    "NewsFetcher",
    "RatingFetcher",
    "ResearchFetcher",
]
