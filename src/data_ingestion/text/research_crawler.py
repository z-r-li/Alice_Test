"""
研报爬虫 - 从配置的券商来源获取研报摘要

参考 PRD 4.1.2 节（软数据规格）和 5.1 节（爬虫配置）实现。
支持 use_mock 参数控制是否使用模拟数据。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from ..models import TextItem
from .base import TextProvider
from .models import TextSourceType

if TYPE_CHECKING:
    from .mock_provider import MockTextProvider

logger = logging.getLogger(__name__)


class ResearchCrawler(TextProvider):
    """
    研报数据爬虫

    从配置的券商来源获取研报摘要，提取摘要、投资要点和风险提示。

    Attributes:
        EXTRACT_PATTERNS: PRD 7.1 定义的关键内容提取正则模式
    """

    # PRD 7.1 节定义的提取模式
    EXTRACT_PATTERNS: ClassVar[list[str]] = [
        r"摘要[：:](.*?)(?=\n\n|\Z)",
        r"投资要点[：:](.*?)(?=\n\n|\Z)",
        r"风险提示[：:](.*?)(?=\n\n|\Z)",
        r"结论[：:](.*?)(?=\n\n|\Z)",
    ]

    # 需要过滤的无观点内容关键词（PRD 4.1.2）
    FILTER_KEYWORDS: ClassVar[list[str]] = [
        "融资融券",
        "大宗交易",
        "股东减持",
        "限售解禁",
        "公告",
    ]

    def __init__(
        self,
        providers: list[str],
        search_entrypoints: list[str] | None = None,
        use_mock: bool = False,
    ):
        """
        初始化研报爬虫

        Args:
            providers: 允许的研报来源列表，如 ["中信证券", "华泰证券", "Morgan Stanley"]
            search_entrypoints: 搜索入口 URL 列表
            use_mock: 是否使用模拟数据（MVP 阶段设为 True）
        """
        self._providers = providers
        self._search_entrypoints = search_entrypoints or []
        self._use_mock = use_mock
        self._mock_provider: MockTextProvider | None = None

        if use_mock:
            from .mock_provider import MockTextProvider
            self._mock_provider = MockTextProvider(data_type="research")

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        获取研报摘要

        根据 ticker/name 构建搜索关键词，在 search_entrypoints 中搜索，
        只保留 providers 列表中的来源，提取摘要/投资建议/风险提示。

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"
            lookback_hours: 时间窗口（小时），默认 48
            max_items: 最大条数，默认 10

        Returns:
            list[TextItem]: 研报摘要列表，按发布时间倒序排列

        Raises:
            NotImplementedError: 当 use_mock=False 时，实际爬取逻辑尚未实现
        """
        logger.info(f"Fetching research reports for {ticker} ({name})")

        # 使用模拟数据
        if self._use_mock and self._mock_provider:
            logger.debug("Using mock data provider")
            return self._mock_provider.fetch_texts(
                ticker, name, lookback_hours, max_items
            )

        # 1. 构建搜索关键词
        queries = self._build_search_queries(ticker, name)
        logger.debug(f"Search queries: {queries}")

        # 2. 获取时间窗口
        start_time, end_time = self._get_time_window(lookback_hours)

        # 3. 搜索研报（MVP 阶段返回模拟数据）
        raw_results = self._search_research_reports(queries, start_time, end_time)

        # 4. 过滤只保留 providers 中的来源
        filtered_results = self._filter_by_providers(raw_results)

        # 5. 过滤无观点内容
        filtered_results = self._filter_low_signal_content(filtered_results)

        # 6. 提取关键内容并构建 TextItem
        text_items = []
        for result in filtered_results[:max_items]:
            summary = self._extract_key_content(result.get("content", ""))
            if not summary:
                summary = result.get("summary", "")

            item = TextItem(
                source=result["source"],
                type="research",
                title=result["title"],
                summary=summary,
                published_at=result["published_at"],
                url=result.get("url"),
            )
            text_items.append(item)

        # 按发布时间倒序排列
        text_items.sort(key=lambda x: x.published_at, reverse=True)

        logger.info(f"Found {len(text_items)} research reports for {ticker}")
        return text_items

    def get_source_name(self) -> str:
        """返回数据源名称"""
        return "research"

    def supports_market(self, ticker: str) -> bool:
        """
        判断该 Provider 是否支持指定市场的 ticker

        ResearchCrawler 目前支持所有市场（占位实现，后续废弃）

        Args:
            ticker: 证券代码

        Returns:
            bool: 始终返回 True
        """
        return True

    def get_supported_source_types(self) -> list[TextSourceType]:
        """
        返回该 Provider 支持的所有数据源类型

        Returns:
            list[TextSourceType]: 仅支持 RESEARCH 类型
        """
        return [TextSourceType.RESEARCH]

    def _build_search_queries(self, ticker: str, name: str) -> list[str]:
        """
        构建搜索关键词

        生成中英文搜索词，覆盖研报、投资建议等多种表述。

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"

        Returns:
            list[str]: 搜索关键词列表

        Examples:
            >>> crawler = ResearchCrawler(providers=["中信证券"])
            >>> queries = crawler._build_search_queries("601985.SH", "中国核电")
            >>> "中国核电 研报" in queries
            True
            >>> "601985 投资建议" in queries
            True
        """
        # 提取纯代码（去除市场后缀）
        pure_ticker = ticker.split(".")[0] if "." in ticker else ticker

        queries = []

        # 中文搜索词
        cn_suffixes = ["研报", "研究报告", "投资建议", "深度报告", "投资评级"]
        for suffix in cn_suffixes:
            queries.append(f"{name} {suffix}")
            queries.append(f"{pure_ticker} {suffix}")

        # 英文搜索词（用于港美股和国际券商研报）
        en_suffixes = ["research report", "investment rating", "analysis"]
        for suffix in en_suffixes:
            queries.append(f"{name} {suffix}")
            queries.append(f"{pure_ticker} {suffix}")

        return queries

    def _extract_key_content(self, content: str) -> str:
        """
        从研报全文提取关键内容

        使用 PRD 7.1 定义的正则模式提取摘要、投资要点、风险提示等。

        Args:
            content: 研报全文内容

        Returns:
            str: 提取的关键内容，多个段落用换行分隔
        """
        if not content:
            return ""

        extracted_parts = []

        for pattern in self.EXTRACT_PATTERNS:
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                cleaned = match.strip()
                if cleaned and len(cleaned) > 10:  # 过滤过短的匹配
                    extracted_parts.append(cleaned)

        return "\n\n".join(extracted_parts)

    def _filter_by_providers(self, results: list[dict]) -> list[dict]:
        """
        过滤只保留 providers 列表中的来源

        Args:
            results: 原始搜索结果列表

        Returns:
            list[dict]: 过滤后的结果
        """
        if not self._providers:
            return results

        return [r for r in results if r.get("source") in self._providers]

    def _filter_low_signal_content(self, results: list[dict]) -> list[dict]:
        """
        过滤无观点内容

        剔除融资融券公告、大宗交易通知等无观点内容（PRD 4.1.2）。

        Args:
            results: 原始结果列表

        Returns:
            list[dict]: 过滤后的结果
        """
        filtered = []
        for result in results:
            title = result.get("title", "")
            # 检查标题是否包含需要过滤的关键词
            if not any(kw in title for kw in self.FILTER_KEYWORDS):
                filtered.append(result)
        return filtered

    def _search_research_reports(
        self,
        queries: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """
        搜索研报

        实际实现需要：
        1. 遍历 search_entrypoints 进行搜索
        2. 解析搜索结果页面
        3. 提取研报链接和基本信息
        4. 访问研报详情页获取全文

        Args:
            queries: 搜索关键词列表
            start_time: 时间窗口开始
            end_time: 时间窗口结束

        Returns:
            list[dict]: 研报数据列表，每项包含 source, title, content, published_at, url

        Raises:
            NotImplementedError: 实际爬取逻辑尚未实现，请使用 use_mock=True
        """
        # 实际爬虫逻辑尚未实现
        # 需要实现：
        # - requests/httpx 进行 HTTP 请求
        # - BeautifulSoup/lxml 解析 HTML
        # - 处理反爬措施
        # - 使用 LLM 辅助提取结构化信息
        raise NotImplementedError(
            "实际研报爬取逻辑尚未实现，请在初始化时设置 use_mock=True 使用模拟数据。"
            "如需使用真实数据，请参考 PRD 5.1 节实现具体的爬虫逻辑。"
        )

