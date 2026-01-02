"""
Serper.dev 搜索客户端

职责：
1. 封装 Serper API 调用
2. 处理搜索结果解析
3. 错误处理和重试
"""
import os
import time
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("alice_test")


@dataclass
class SearchResult:
    """搜索结果项"""
    title: str
    link: str
    snippet: str
    position: int
    domain: str  # 从 link 中提取的域名


class SerperClient:
    """
    Serper.dev 搜索客户端

    API 文档: https://serper.dev/docs
    免费额度: 2,500 次/月
    """

    BASE_URL = "https://google.serper.dev/search"
    NEWS_URL = "https://google.serper.dev/news"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
    ):
        """
        初始化客户端

        Args:
            api_key: Serper API 密钥，None 则从环境变量 SERPER_API_KEY 读取
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        self._api_key = api_key or os.getenv("SERPER_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Serper API key is required. "
                "Set SERPER_API_KEY environment variable or pass api_key parameter."
            )
        self._timeout = timeout
        self._max_retries = max_retries

    def search(
        self,
        query: str,
        num_results: int = 10,
        country: str = "us",
        language: str = "en",
    ) -> list[SearchResult]:
        """
        执行 Google 搜索

        Args:
            query: 搜索查询
            num_results: 返回结果数量 (1-100)
            country: 搜索国家代码 (us, hk, cn 等)
            language: 搜索语言 (en, zh 等)

        Returns:
            list[SearchResult]: 搜索结果列表

        Raises:
            httpx.HTTPError: API 请求失败
            ValueError: 参数无效
        """
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")

        num_results = max(1, min(100, num_results))

        payload = {
            "q": query,
            "num": num_results,
            "gl": country,
            "hl": language,
        }

        logger.debug(f"Searching for: {query}")
        response_data = self._make_request(self.BASE_URL, payload)

        results = []
        organic = response_data.get("organic", [])

        for item in organic:
            link = item.get("link", "")
            result = SearchResult(
                title=item.get("title", ""),
                link=link,
                snippet=item.get("snippet", ""),
                position=item.get("position", 0),
                domain=self._extract_domain(link),
            )
            results.append(result)

        logger.info(f"Search completed: query='{query}', results={len(results)}")
        return results

    def search_news(
        self,
        query: str,
        num_results: int = 10,
        country: str = "us",
        language: str = "en",
    ) -> list[SearchResult]:
        """
        搜索新闻

        使用 Serper 的新闻搜索端点

        Args:
            query: 搜索查询
            num_results: 返回结果数量 (1-100)
            country: 搜索国家代码 (us, hk, cn 等)
            language: 搜索语言 (en, zh 等)

        Returns:
            list[SearchResult]: 新闻搜索结果列表

        Raises:
            httpx.HTTPError: API 请求失败
            ValueError: 参数无效
        """
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")

        num_results = max(1, min(100, num_results))

        payload = {
            "q": query,
            "num": num_results,
            "gl": country,
            "hl": language,
        }

        logger.debug(f"Searching news for: {query}")
        response_data = self._make_request(self.NEWS_URL, payload)

        results = []
        news = response_data.get("news", [])

        for idx, item in enumerate(news, start=1):
            link = item.get("link", "")
            result = SearchResult(
                title=item.get("title", ""),
                link=link,
                snippet=item.get("snippet", ""),
                position=item.get("position", idx),
                domain=self._extract_domain(link),
            )
            results.append(result)

        logger.info(f"News search completed: query='{query}', results={len(results)}")
        return results

    def _extract_domain(self, url: str) -> str:
        """从 URL 提取域名"""
        if not url:
            return ""
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")

    def _make_request(
        self,
        endpoint: str,
        payload: dict,
    ) -> dict:
        """
        发送 API 请求（带重试）

        Args:
            endpoint: API 端点 URL
            payload: 请求体

        Returns:
            dict: API 响应

        Raises:
            httpx.HTTPError: 请求失败（重试后仍失败）
        """
        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

        last_error: httpx.HTTPError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        endpoint,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    f"Serper API request failed (attempt {attempt + 1}/{self._max_retries + 1}): {e}"
                )
                if attempt < self._max_retries:
                    sleep_time = 1 * (attempt + 1)  # 线性退避: 1s, 2s, 3s...
                    time.sleep(sleep_time)

        logger.error(f"Serper API request failed after {self._max_retries + 1} attempts")
        raise last_error  # type: ignore[misc]
