"""
A 股公告获取器（#65/#66 新增共识数据源）

数据源: 巨潮资讯 (cninfo) — AkShare `stock_zh_a_disclosure_report_cninfo`
用途: 补充「公告/披露」这一信息源，缓解「现有源 + 时间窗常信息不足」的问题。
任何获取/解析失败都优雅降级为空列表（不影响其他数据源）。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import pandas as pd

from ...models import TextItem
from ..base import TextProvider
from ..models import TextSourceType

logger = logging.getLogger("alice_test")


def _first(row, *names: str) -> str:
    """从 row（pandas Series / dict）按候选列名取第一个非空值"""
    for n in names:
        try:
            val = row[n]
        except (KeyError, TypeError, IndexError):
            continue
        if val is not None and str(val).strip() not in ("", "nan", "None", "-"):
            return str(val).strip()
    return ""


def _parse_dt(value) -> datetime | None:
    """宽松解析日期/时间，失败返回 None"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    s = str(value).strip()
    if not s or s in ("nan", "None", "-"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 4], fmt)
        except ValueError:
            continue
    return None


class AnnouncementFetcher(TextProvider):
    """巨潮资讯公告获取器"""

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        if not self.supports_market(ticker):
            logger.warning(f"[{ticker}] 非 A 股，AnnouncementFetcher 不支持")
            return []

        symbol = self.extract_symbol(ticker)
        end = datetime.now()
        start = end - timedelta(hours=lookback_hours)

        try:
            import akshare as ak

            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=symbol,
                market="沪深京",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as e:
            logger.warning(f"[{ticker}] 公告获取失败: {e}")
            return []

        if df is None or getattr(df, "empty", True):
            logger.debug(f"[{ticker}] 无公告数据")
            return []

        return self._to_items(df, lookback_hours, max_items)

    def _to_items(
        self, df: pd.DataFrame, lookback_hours: int, max_items: int
    ) -> list[TextItem]:
        cutoff = datetime.now() - timedelta(hours=lookback_hours)
        rows: list[tuple[datetime, TextItem]] = []
        for _, row in df.iterrows():
            title = _first(row, "公告标题", "title", "标题")
            if not title:
                continue
            published = _parse_dt(
                _first(row, "公告时间", "公告日期", "date", "time") or None
            )
            if published is None:
                continue
            if published < cutoff:
                continue
            ann_type = _first(row, "公告类型", "类型")
            url = _first(row, "公告链接", "url", "链接") or None
            summary = f"公告类型: {ann_type} | {title}" if ann_type else f"公告: {title}"
            rows.append(
                (
                    published,
                    TextItem(
                        source="巨潮公告",
                        type="news",
                        title=title,
                        summary=summary,
                        published_at=published,
                        url=url,
                    ),
                )
            )

        rows.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in rows[:max_items]]

    def get_source_name(self) -> str:
        return "巨潮公告"

    def supports_market(self, ticker: str) -> bool:
        return self.detect_market(ticker) == "a_share"

    def get_supported_source_types(self) -> list[TextSourceType]:
        return [TextSourceType.ANNOUNCEMENT]
