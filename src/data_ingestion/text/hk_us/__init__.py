"""
港美股文本数据采集模块

基于 Web Search (Serper.dev) 实现港美股市场的文本数据获取。

组件：
- SerperClient: Serper.dev 搜索客户端
- WebFetcher: 网页内容抓取器
- AgentBrowser: LLM 驱动的多层浏览器
- HKUSTextProvider: 港美股文本数据提供器（顶层封装）
"""

from .serper_client import SerperClient, SearchResult
from .web_fetcher import WebFetcher, PageContent
from .agent_browser import AgentBrowser, BrowseResult
from .hk_us_provider import HKUSTextProvider

__all__ = [
    "SerperClient",
    "SearchResult",
    "WebFetcher",
    "PageContent",
    "AgentBrowser",
    "BrowseResult",
    "HKUSTextProvider",
]
