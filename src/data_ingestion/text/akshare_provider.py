"""
AkShare A股文本数据提供者

整合新闻和研报数据源
"""
import logging
from typing import List

from ..models import TextItem
from .base import TextProvider
from .akshare.news_fetcher import AkShareNewsFetcher
from .akshare.research_fetcher import AkShareResearchFetcher
from .akshare.pdf_extractor import PDFExtractor

logger = logging.getLogger("alice_test")


class AkShareTextProvider(TextProvider):
    """AkShare A股文本数据提供者"""

    def __init__(
        self,
        llm_client=None,
        extract_pdf: bool = True,
        news_weight: float = 0.4,
        research_weight: float = 0.6,
    ):
        """
        初始化 AkShare 数据提供者

        Args:
            llm_client: DeepSeekClient 实例（用于 PDF 摘要提取）
            extract_pdf: 是否解析研报 PDF 内容
            news_weight: 新闻数量占比
            research_weight: 研报数量占比
        """
        self._news_fetcher = AkShareNewsFetcher()

        # PDF 提取器
        pdf_extractor = None
        if extract_pdf:
            pdf_extractor = PDFExtractor(llm_client=llm_client, use_llm=True)

        self._research_fetcher = AkShareResearchFetcher(
            pdf_extractor=pdf_extractor,
            extract_pdf=extract_pdf,
        )

        self._news_weight = news_weight
        self._research_weight = research_weight

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> List[TextItem]:
        """
        获取 A 股标的的新闻和研报

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称（本接口未使用）
            lookback_hours: 回溯小时数
            max_items: 最大返回条数

        Returns:
            List[TextItem]: 文本数据列表
        """
        # 提取纯代码（去除后缀）
        symbol = self._extract_symbol(ticker)
        if not symbol:
            logger.warning(f"[{ticker}] 非 A 股代码，跳过 AkShare")
            return []

        # 计算新闻和研报的配额
        news_quota = max(1, int(max_items * self._news_weight))
        research_quota = max(1, int(max_items * self._research_weight))

        # 并行获取（可优化为异步）
        news_items = self._news_fetcher.fetch(
            symbol=symbol,
            lookback_hours=lookback_hours,
            max_items=news_quota,
        )

        research_items = self._research_fetcher.fetch(
            symbol=symbol,
            lookback_hours=lookback_hours,
            max_items=research_quota,
        )

        # 合并并按时间排序
        all_items = news_items + research_items
        all_items.sort(key=lambda x: x.published_at, reverse=True)

        logger.info(
            f"[{ticker}] AkShare 获取完成: "
            f"{len(news_items)} 条新闻, {len(research_items)} 条研报"
        )

        return all_items[:max_items]

    def get_source_name(self) -> str:
        return "akshare"

    def _extract_symbol(self, ticker: str) -> str | None:
        """
        从 ticker 提取纯数字代码

        "601985.SH" -> "601985"
        "000001.SZ" -> "000001"
        "0700.HK" -> None (非 A 股)
        """
        ticker = ticker.upper()
        if ticker.endswith((".SH", ".SZ")):
            return ticker.split(".")[0]

        # 检查是否为纯数字 A 股代码
        code = ticker.split(".")[0]
        if code.isdigit() and len(code) == 6:
            return code

        return None

    @staticmethod
    def is_a_share(ticker: str) -> bool:
        """判断是否为 A 股代码"""
        ticker = ticker.upper()
        return ticker.endswith((".SH", ".SZ"))
