"""
新闻爬虫 - 从配置的新闻站点获取标题和摘要

参考 PRD 4.1.2 节（软数据规格）和 5.1 节（爬虫配置）实现。
MVP 阶段返回模拟数据，实际爬虫需根据具体数据源调整。
"""
import logging
from datetime import datetime, timedelta
from typing import ClassVar

from ..models import TextItem
from .base import TextProvider

logger = logging.getLogger(__name__)


class NewsCrawler(TextProvider):
    """
    新闻数据爬虫

    从配置的新闻站点获取新闻标题和摘要，过滤非观点类内容。

    Attributes:
        TRUSTED_SOURCES: PRD 5.1 定义的可信新闻源
        FILTER_KEYWORDS: PRD 4.1.2 定义的需过滤的内容关键词
    """

    # PRD 5.1 节定义的可信源
    TRUSTED_SOURCES: ClassVar[dict[str, list[str]]] = {
        "cn": ["eastmoney.com", "10jqka.com.cn", "wind.com.cn"],
        "en": ["bloomberg.com", "reuters.com"],
    }

    # PRD 5.1 节定义的源名称映射
    SOURCE_NAMES: ClassVar[dict[str, str]] = {
        "eastmoney.com": "东方财富",
        "10jqka.com.cn": "同花顺",
        "wind.com.cn": "万得",
        "bloomberg.com": "Bloomberg",
        "reuters.com": "Reuters",
    }

    # PRD 4.1.2 节定义的需要过滤的无观点内容关键词
    FILTER_KEYWORDS: ClassVar[list[str]] = [
        "融资融券",
        "大宗交易",
        "股东减持",
        "限售股解禁",
        "限售解禁",
        "交易公开信息",
        "龙虎榜",
        "公告",
        "通知",
    ]

    def __init__(
        self,
        news_sites: list[str],
        search_entrypoints: list[str] | None = None,
    ):
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

        根据 ticker/name 构建搜索关键词，在 news_sites / search_entrypoints 中搜索，
        过滤非观点类内容，提取标题和关键内容。

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"
            lookback_hours: 时间窗口（小时），默认 48
            max_items: 最大条数，默认 10

        Returns:
            list[TextItem]: 新闻列表，按发布时间倒序排列
        """
        logger.info(f"Fetching news for {ticker} ({name})")

        # 1. 构建搜索关键词
        queries = self._build_search_queries(ticker, name)
        logger.debug(f"Search queries: {queries}")

        # 2. 获取时间窗口
        start_time, end_time = self._get_time_window(lookback_hours)

        # 3. 搜索新闻（MVP 阶段返回模拟数据）
        raw_results = self._search_news(queries, start_time, end_time)

        # 4. 过滤只保留 news_sites 中的来源
        filtered_results = self._filter_by_sources(raw_results)

        # 5. 过滤非观点类内容
        filtered_results = self._filter_low_signal_content(filtered_results)

        # 6. 构建 TextItem 列表
        text_items = []
        for result in filtered_results[:max_items]:
            item = TextItem(
                source=result["source"],
                type="news",
                title=result["title"],
                summary=result.get("summary", ""),
                published_at=result["published_at"],
                url=result.get("url"),
            )
            text_items.append(item)

        # 按发布时间倒序排列
        text_items.sort(key=lambda x: x.published_at, reverse=True)

        logger.info(f"Found {len(text_items)} news items for {ticker}")
        return text_items

    def get_source_name(self) -> str:
        """返回数据源名称"""
        return "news"

    def _build_search_queries(self, ticker: str, name: str) -> list[str]:
        """
        构建搜索关键词

        生成中英文搜索词，覆盖新闻、资讯等多种表述。

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"

        Returns:
            list[str]: 搜索关键词列表

        Examples:
            >>> crawler = NewsCrawler(news_sites=["东方财富"])
            >>> queries = crawler._build_search_queries("601985.SH", "中国核电")
            >>> "中国核电" in queries
            True
        """
        # 提取纯代码（去除市场后缀）
        pure_ticker = ticker.split(".")[0] if "." in ticker else ticker

        queries = []

        # 基础搜索词
        queries.append(name)
        queries.append(pure_ticker)

        # 中文搜索词
        cn_suffixes = ["新闻", "资讯", "快讯", "动态"]
        for suffix in cn_suffixes:
            queries.append(f"{name} {suffix}")

        # 英文搜索词（用于港美股和国际媒体）
        en_suffixes = ["news", "update", "analysis"]
        for suffix in en_suffixes:
            queries.append(f"{name} {suffix}")
            queries.append(f"{pure_ticker} {suffix}")

        return queries

    def _filter_by_sources(self, results: list[dict]) -> list[dict]:
        """
        过滤只保留 news_sites 列表中的来源

        Args:
            results: 原始搜索结果列表

        Returns:
            list[dict]: 过滤后的结果
        """
        if not self._news_sites:
            return results

        return [r for r in results if r.get("source") in self._news_sites]

    def _filter_low_signal_content(self, results: list[dict]) -> list[dict]:
        """
        过滤非观点类内容

        剔除融资融券公告、大宗交易通知、龙虎榜等无观点内容（PRD 4.1.2）。

        Args:
            results: 原始结果列表

        Returns:
            list[dict]: 过滤后的结果
        """
        filtered = []
        for result in results:
            title = result.get("title", "")
            summary = result.get("summary", "")
            content = title + summary

            # 检查标题或摘要是否包含需要过滤的关键词
            if not any(kw in content for kw in self.FILTER_KEYWORDS):
                filtered.append(result)
            else:
                logger.debug(f"Filtered out low-signal content: {title}")

        return filtered

    def _search_news(
        self,
        queries: list[str],
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """
        搜索新闻

        MVP 阶段返回模拟数据。实际实现需要：
        1. 遍历 search_entrypoints 进行搜索
        2. 解析搜索结果页面
        3. 提取新闻链接和基本信息
        4. 访问新闻详情页获取正文

        Args:
            queries: 搜索关键词列表
            start_time: 时间窗口开始
            end_time: 时间窗口结束

        Returns:
            list[dict]: 新闻数据列表，每项包含 source, title, summary, published_at, url
        """
        # MVP: 返回模拟数据
        # TODO: 实现实际爬虫逻辑，可能需要：
        # - requests/httpx 进行 HTTP 请求
        # - BeautifulSoup/lxml 解析 HTML
        # - 处理反爬措施
        # - 使用 LLM 辅助提取结构化信息

        logger.debug("Using mock data for MVP stage")

        # 模拟数据 - 展示数据结构
        mock_results = [
            {
                "source": "东方财富",
                "title": "中国核电：AI算力需求推动核电板块持续走强",
                "summary": "受AI数据中心电力需求增长预期影响，核电板块持续获得市场关注。"
                "中国核电作为行业龙头，近期获得机构密集调研。分析人士指出，"
                "核电具有稳定、清洁、低成本的特点，是支撑AI算力发展的理想电力来源。",
                "published_at": end_time - timedelta(hours=2),
                "url": "https://finance.eastmoney.com/news/001",
            },
            {
                "source": "同花顺",
                "title": "核电审批加速，中国核电在建机组规模领先",
                "summary": "国家能源局近期核准多个核电项目，核电建设进入加速期。"
                "中国核电在建机组数量和规模均处于行业领先地位，"
                "未来几年将迎来机组集中投产期。",
                "published_at": end_time - timedelta(hours=8),
                "url": "https://news.10jqka.com.cn/news/002",
            },
            {
                "source": "Bloomberg",
                "title": "China Nuclear Power Gains as AI Demand Boosts Outlook",
                "summary": "China Nuclear Power Corp. shares rose as investors bet on "
                "increasing electricity demand from artificial intelligence data centers. "
                "The company operates the largest fleet of nuclear reactors in China.",
                "published_at": end_time - timedelta(hours=18),
                "url": "https://www.bloomberg.com/news/003",
            },
            {
                "source": "Reuters",
                "title": "China's nuclear power sector sees renewed growth momentum",
                "summary": "China's nuclear power industry is experiencing a resurgence "
                "as the country accelerates its clean energy transition. "
                "New reactor approvals have reached the highest level in years.",
                "published_at": end_time - timedelta(hours=30),
                "url": "https://www.reuters.com/news/004",
            },
            # 以下是应该被过滤掉的内容示例
            {
                "source": "东方财富",
                "title": "中国核电融资融券信息(12-19)",
                "summary": "12月19日，中国核电融资融券信息显示，融资余额为...",
                "published_at": end_time - timedelta(hours=4),
                "url": "https://finance.eastmoney.com/news/005",
            },
            {
                "source": "同花顺",
                "title": "中国核电：关于股东减持公告",
                "summary": "本公司股东计划减持不超过...",
                "published_at": end_time - timedelta(hours=10),
                "url": "https://news.10jqka.com.cn/news/006",
            },
            {
                "source": "东方财富",
                "title": "中国核电龙虎榜：机构净买入2.5亿",
                "summary": "12月19日龙虎榜数据显示...",
                "published_at": end_time - timedelta(hours=5),
                "url": "https://finance.eastmoney.com/news/007",
            },
        ]

        # 过滤时间窗口内的结果
        return [
            r for r in mock_results if start_time <= r["published_at"] <= end_time
        ]
