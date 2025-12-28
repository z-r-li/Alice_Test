"""
AkShare A股文本数据获取模块

包含新闻、研报获取器和PDF解析器
"""
from .news_fetcher import AkShareNewsFetcher
from .research_fetcher import AkShareResearchFetcher
from .pdf_extractor import PDFExtractor

__all__ = [
    "AkShareNewsFetcher",
    "AkShareResearchFetcher",
    "PDFExtractor",
]
