"""
港美股文本数据采集模块

包含:
- Serper.dev 搜索客户端（Google Search API）
- SEC/HKEX 公告获取（TODO）
- 英文财经新闻采集（TODO）
- 海外研报获取（TODO）
"""

from .serper_client import SearchResult, SerperClient

__all__: list[str] = [
    "SearchResult",
    "SerperClient",
]
