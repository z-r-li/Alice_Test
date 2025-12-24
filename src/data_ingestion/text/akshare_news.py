"""
AkShare A股新闻数据提供者

基于 AkShare 的免费接口获取东方财富个股新闻。
仅支持 A 股（.SH / .SZ 后缀）。
"""
import logging
import re
import time
from datetime import datetime

import akshare as ak
import pandas as pd

from ..models import TextItem
from .base import TextProvider

logger = logging.getLogger(__name__)


class AkShareNewsProvider(TextProvider):
    """
    AkShare A股新闻数据提供者

    通过 AkShare 调用东方财富的个股新闻接口获取新闻数据。

    Attributes:
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）

    Example:
        >>> provider = AkShareNewsProvider()
        >>> news = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=48)
        >>> for item in news:
        ...     print(f"{item.title} - {item.source}")
    """

    # 支持的市场后缀
    SUPPORTED_SUFFIXES = (".SH", ".SZ")

    def __init__(self, max_retries: int = 2, retry_delay: float = 1.0):
        """
        初始化 AkShare 新闻提供者

        Args:
            max_retries: 网络请求最大重试次数，默认 2 次
            retry_delay: 重试间隔秒数，默认 1.0 秒
        """
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取指定 A 股标的的新闻数据

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"
            lookback_hours: 回溯时间窗口（小时），默认 48 小时
            max_items: 最大返回条数，默认 10 条

        Returns:
            list[TextItem]: 新闻数据列表，按时间倒序排列

        Notes:
            - 仅支持 A 股（.SH / .SZ 后缀）
            - 港股和美股会返回空列表
            - 网络错误会重试，最终失败返回空列表
        """
        ticker_upper = ticker.upper().strip()

        # 检查是否为 A 股
        if not self._is_a_share(ticker_upper):
            logger.warning(
                f"AkShare 仅支持 A 股，{ticker_upper} 不是有效的 A 股代码"
            )
            return []

        # 提取纯股票代码（去掉后缀）
        stock_code = self._extract_stock_code(ticker_upper)

        # 计算时间窗口
        start_time, end_time = self._get_time_window(lookback_hours)

        logger.info(
            f"Fetching AkShare news for {ticker_upper} ({name}), "
            f"lookback={lookback_hours}h, max_items={max_items}"
        )

        # 获取新闻数据
        df = self._fetch_news_with_retry(stock_code)

        if df is None or df.empty:
            logger.info(f"No news found for {ticker_upper}")
            return []

        # 转换为 TextItem 列表
        text_items = self._convert_to_text_items(df, start_time, end_time, max_items)

        logger.info(f"Returned {len(text_items)} news items for {ticker_upper}")
        return text_items

    def get_source_name(self) -> str:
        """返回数据源名称"""
        return "东方财富"

    def _is_a_share(self, ticker: str) -> bool:
        """
        检查是否为 A 股代码

        Args:
            ticker: 证券代码

        Returns:
            bool: 是否为 A 股
        """
        return ticker.endswith(self.SUPPORTED_SUFFIXES)

    def _extract_stock_code(self, ticker: str) -> str:
        """
        从 ticker 提取纯股票代码

        Args:
            ticker: 完整证券代码，如 "601985.SH"

        Returns:
            str: 纯股票代码，如 "601985"
        """
        # 移除后缀
        for suffix in self.SUPPORTED_SUFFIXES:
            if ticker.endswith(suffix):
                return ticker[: -len(suffix)]
        return ticker

    def _fetch_news_with_retry(self, stock_code: str) -> pd.DataFrame | None:
        """
        带重试机制的新闻获取

        Args:
            stock_code: 纯股票代码

        Returns:
            DataFrame | None: 新闻数据，失败返回 None
        """
        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                df = ak.stock_news_em(symbol=stock_code)
                return df

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 检查是否为限流错误
                if "频率" in error_msg or "限制" in error_msg or "rate" in error_msg.lower():
                    logger.warning(
                        f"AkShare rate limited, attempt {attempt + 1}/{self._max_retries + 1}"
                    )
                    # 限流时等待更长时间
                    time.sleep(self._retry_delay * 2)
                else:
                    logger.warning(
                        f"AkShare request failed, attempt {attempt + 1}/{self._max_retries + 1}: {e}"
                    )
                    time.sleep(self._retry_delay)

        # 所有重试都失败
        logger.error(f"AkShare request failed after {self._max_retries + 1} attempts: {last_error}")
        return None

    def _convert_to_text_items(
        self,
        df: pd.DataFrame,
        start_time: datetime,
        end_time: datetime,
        max_items: int,
    ) -> list[TextItem]:
        """
        将 DataFrame 转换为 TextItem 列表

        Args:
            df: AkShare 返回的新闻 DataFrame
            start_time: 时间窗口开始
            end_time: 时间窗口结束
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 转换后的文本数据列表
        """
        text_items = []

        for _, row in df.iterrows():
            try:
                # 解析发布时间
                published_at = self._parse_datetime(row.get("发布时间", ""))

                if published_at is None:
                    continue

                # 过滤时间范围
                if published_at < start_time or published_at > end_time:
                    continue

                # 提取字段
                title = str(row.get("新闻标题", "")).strip()
                content = str(row.get("新闻内容", "")).strip()
                url = str(row.get("新闻链接", "")).strip() or None
                source = str(row.get("文章来源", "东方财富")).strip()

                if not title:
                    continue

                # 生成摘要：取内容前 200 字
                summary = self._generate_summary(content, title)

                item = TextItem(
                    source=source if source else "东方财富",
                    type="news",
                    title=title,
                    summary=summary,
                    published_at=published_at,
                    url=url if url and url != "nan" else None,
                )
                text_items.append(item)

            except Exception as e:
                logger.debug(f"Error converting row to TextItem: {e}")
                continue

        # 按时间倒序排列
        text_items.sort(key=lambda x: x.published_at, reverse=True)

        # 限制返回条数
        return text_items[:max_items]

    def _parse_datetime(self, dt_str: str) -> datetime | None:
        """
        解析日期时间字符串

        AkShare 返回的时间格式可能有多种，需要尝试多种解析方式。

        Args:
            dt_str: 日期时间字符串

        Returns:
            datetime | None: 解析后的 datetime，失败返回 None
        """
        if not dt_str or pd.isna(dt_str):
            return None

        dt_str = str(dt_str).strip()

        # 尝试多种日期格式
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y年%m月%d日 %H:%M:%S",
            "%Y年%m月%d日 %H:%M",
            "%m-%d %H:%M",  # 当年的简化格式
        ]

        for fmt in formats:
            try:
                parsed = datetime.strptime(dt_str, fmt)
                # 如果年份缺失，补充当年
                if parsed.year == 1900:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed
            except ValueError:
                continue

        # 尝试使用 pandas 解析
        try:
            parsed = pd.to_datetime(dt_str)
            if pd.notna(parsed):
                return parsed.to_pydatetime()
        except Exception:
            pass

        logger.debug(f"Failed to parse datetime: {dt_str}")
        return None

    def _generate_summary(self, content: str, title: str) -> str:
        """
        生成新闻摘要

        优先使用内容的前 200 字，如果内容为空则使用标题。

        Args:
            content: 新闻内容
            title: 新闻标题

        Returns:
            str: 摘要文本
        """
        if not content or content == "nan" or len(content.strip()) == 0:
            return title

        # 清理内容：移除多余空白
        cleaned = re.sub(r"\s+", " ", content).strip()

        # 截取前 200 字
        if len(cleaned) > 200:
            # 尝试在标点处截断
            truncated = cleaned[:200]
            last_punct = max(
                truncated.rfind("。"),
                truncated.rfind("！"),
                truncated.rfind("？"),
                truncated.rfind("；"),
            )
            if last_punct > 100:
                return truncated[: last_punct + 1]
            return truncated + "..."

        return cleaned
