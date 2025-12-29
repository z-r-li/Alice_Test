"""
A 股新闻获取器

数据源: 东方财富 (stock_news_em)
接口: AkShare stock_news_em
限量: 单次返回近 100 条新闻
"""

from datetime import datetime, timedelta
import logging

import pandas as pd

from ...models import TextItem
from ..models import FetchResult, TextSourceType

logger = logging.getLogger("alice_test")


class NewsFetcher:
    """
    A 股新闻获取器

    数据源: 东方财富 (stock_news_em)
    限量: 单次返回近 100 条新闻

    Example:
        >>> fetcher = NewsFetcher()
        >>> result = fetcher.fetch(
        ...     ticker="601985.SH",
        ...     symbol="601985",
        ...     name="中国核电",
        ...     lookback_hours=72,
        ...     max_items=5,
        ... )
        >>> print(f"Success: {result.success}, Count: {result.fetch_count}")
    """

    def fetch(
        self,
        ticker: str,
        symbol: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> FetchResult:
        """
        获取个股新闻

        Args:
            ticker: 完整代码如 "601985.SH"
            symbol: 纯数字代码如 "601985"
            name: 股票名称
            lookback_hours: 时间窗口（小时）
            max_items: 最大返回条数

        Returns:
            FetchResult: 包含 TextItem 列表和元信息
        """
        import akshare as ak

        logger.debug(f"[{ticker}] 开始获取新闻, lookback={lookback_hours}h, max={max_items}")

        try:
            df = ak.stock_news_em(symbol=symbol)
        except Exception as e:
            error_msg = f"AkShare 新闻获取失败: {e}"
            logger.warning(f"[{ticker}] {error_msg}")
            return FetchResult(
                items=[],
                source_type=TextSourceType.NEWS,
                success=False,
                error_message=error_msg,
                fetch_count=0,
                request_count=max_items,
            )

        if df is None or df.empty:
            logger.debug(f"[{ticker}] 无新闻数据")
            return FetchResult(
                items=[],
                source_type=TextSourceType.NEWS,
                success=True,
                error_message=None,
                fetch_count=0,
                request_count=max_items,
            )

        # 转换为 TextItem 列表
        items = self._convert_to_text_items(df, lookback_hours, max_items)

        logger.info(f"[{ticker}] 获取 {len(items)} 条新闻")
        return FetchResult(
            items=items,
            source_type=TextSourceType.NEWS,
            success=True,
            error_message=None,
            fetch_count=len(items),
            request_count=max_items,
        )

    def _convert_to_text_items(
        self,
        df: pd.DataFrame,
        lookback_hours: int,
        max_items: int,
    ) -> list[TextItem]:
        """
        将 DataFrame 转换为 TextItem 列表

        Args:
            df: AkShare 返回的新闻 DataFrame
            lookback_hours: 回溯时间（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 过滤后的新闻列表
        """
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
        results: list[TextItem] = []

        for _, row in df.iterrows():
            try:
                # 解析发布时间
                published_at = self._parse_datetime(row.get("发布时间", ""))
                if published_at is None:
                    continue

                # 时间过滤
                if published_at < cutoff_time:
                    continue

                # 构建 TextItem
                item = TextItem(
                    source=str(row.get("文章来源", "东方财富")),
                    type="news",
                    title=str(row.get("新闻标题", "")),
                    summary=self._truncate_content(str(row.get("新闻内容", "")), 300),
                    published_at=published_at,
                    url=str(row.get("新闻链接", "")) or None,
                )
                results.append(item)

                if len(results) >= max_items:
                    break

            except Exception as e:
                logger.debug(f"解析新闻行失败: {e}")
                continue

        return results

    def _parse_datetime(self, date_str: str) -> datetime | None:
        """
        解析东方财富的时间格式

        Args:
            date_str: 时间字符串，如 "2024-03-15 18:30:00"

        Returns:
            datetime | None: 解析后的时间，解析失败返回 None
        """
        if not date_str:
            return None

        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(str(date_str), fmt)
            except ValueError:
                continue

        return None

    def _truncate_content(self, content: str, max_length: int = 300) -> str:
        """
        截断过长的新闻内容

        Args:
            content: 原始内容
            max_length: 最大长度，默认 300

        Returns:
            str: 截断后的内容
        """
        content = content.strip()
        if len(content) <= max_length:
            return content
        return content[:max_length] + "..."
