"""
研报爬虫 - 从配置的券商来源获取研报摘要

参考 PRD 4.1.2 节（软数据规格）和 5.1 节（爬虫配置）实现。
MVP 阶段返回模拟数据，实际爬虫需根据具体数据源调整。
"""
import logging
import re
from datetime import datetime, timedelta
from typing import ClassVar

from ..models import TextItem
from .base import TextProvider

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
    ):
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

        根据 ticker/name 构建搜索关键词，在 search_entrypoints 中搜索，
        只保留 providers 列表中的来源，提取摘要/投资建议/风险提示。

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"
            lookback_hours: 时间窗口（小时），默认 48
            max_items: 最大条数，默认 10

        Returns:
            list[TextItem]: 研报摘要列表，按发布时间倒序排列
        """
        logger.info(f"Fetching research reports for {ticker} ({name})")

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

        MVP 阶段返回模拟数据。实际实现需要：
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
                "source": "中信证券",
                "title": "中国核电深度报告：AI算力驱动电力需求增长",
                "content": """
摘要：核电作为稳定基荷电力，将充分受益于AI算力发展带来的电力需求增长。
公司作为国内核电龙头，在建机组规模领先，未来成长确定性高。

投资要点：
1. AI算力中心需要24小时稳定供电，核电是理想选择
2. 公司在运机组容量持续增长，发电量稳步提升
3. 新建机组审批加速，储备项目充足

风险提示：核电政策变化风险；电力市场化改革风险；项目建设进度不及预期。
""",
                "summary": "核电作为稳定基荷电力，将受益于AI算力发展",
                "published_at": end_time - timedelta(hours=6),
                "url": "https://example.com/research/001",
            },
            {
                "source": "华泰证券",
                "title": "中国核电：核电重启加速，龙头地位稳固",
                "content": """
摘要：核电审批重启后，公司作为行业龙头充分受益。维持"买入"评级。

投资要点：公司在建机组数量行业领先，未来三年业绩增长可期。
核电利用小时数高于火电，盈利能力稳定。

风险提示：电价下行风险；核安全事件风险。
""",
                "summary": "核电审批重启，维持买入评级",
                "published_at": end_time - timedelta(hours=12),
                "url": "https://example.com/research/002",
            },
            {
                "source": "Morgan Stanley",
                "title": "China Nuclear Power: Beneficiary of AI Power Demand",
                "content": """
Summary: China Nuclear Power is well-positioned to benefit from rising power demand
driven by AI infrastructure buildout. Maintain Overweight rating.

Investment highlights:
- Nuclear provides stable baseload power essential for data centers
- Company has industry-leading pipeline of units under construction
- Regulatory environment becoming more supportive

Risk factors: Policy changes; construction delays; safety incidents.
""",
                "summary": "Well-positioned to benefit from AI power demand",
                "published_at": end_time - timedelta(hours=24),
                "url": "https://example.com/research/003",
            },
        ]

        # 过滤时间窗口内的结果
        return [
            r for r in mock_results if start_time <= r["published_at"] <= end_time
        ]
