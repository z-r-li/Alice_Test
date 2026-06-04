"""
财联社 (CLS) 电报新闻获取器（#65/#66 新增共识数据源）

数据源: 财联社 — AkShare `stock_telegraph_cls`（全市场电报）
策略: 财联社电报是全市场流，按标的名称 / 代码做子串过滤，取与该标的相关的条目。
用途: 补充高时效财经新闻源；任何失败优雅降级为空列表。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from ...models import TextItem
from ..base import TextProvider
from ..models import TextSourceType
from .announcement_fetcher import _first, _parse_dt

logger = logging.getLogger("alice_test")


class CLSNewsFetcher(TextProvider):
    """财联社电报新闻获取器"""

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        if not self.supports_market(ticker):
            logger.warning(f"[{ticker}] 非 A 股，CLSNewsFetcher 不支持")
            return []

        symbol = self.extract_symbol(ticker)
        try:
            import akshare as ak

            df = ak.stock_telegraph_cls()
        except Exception as e:
            logger.warning(f"[{ticker}] 财联社电报获取失败: {e}")
            return []

        if df is None or getattr(df, "empty", True):
            logger.debug(f"[{ticker}] 无财联社电报数据")
            return []

        return self._to_items(df, name, symbol, lookback_hours, max_items)

    def _to_items(
        self,
        df: pd.DataFrame,
        name: str,
        symbol: str,
        lookback_hours: int,
        max_items: int,
    ) -> list[TextItem]:
        cutoff = datetime.now() - timedelta(hours=lookback_hours)
        rows: list[tuple[datetime, TextItem]] = []

        for _, row in df.iterrows():
            title = _first(row, "标题", "title")
            content = _first(row, "内容", "content")
            blob = f"{title} {content}"
            # 全市场电报 → 仅保留提及该标的（名称或代码）的条目
            if name and name not in blob and symbol not in blob:
                continue
            if not name and symbol not in blob:
                continue

            published = _parse_dt(
                _first(row, "发布时间", "datetime", "time")
                or (
                    f"{_first(row, '发布日期', 'date')} {_first(row, '发布时间', 'time')}".strip()
                    or None
                )
            )
            if published is None:
                # 无法解析时间则保守跳过（不臆造时间）
                continue
            if published < cutoff:
                continue

            display_title = title or (content[:40] if content else "财联社电报")
            rows.append(
                (
                    published,
                    TextItem(
                        source="财联社",
                        type="news",
                        title=display_title,
                        summary=content or display_title,
                        published_at=published,
                        url=None,
                    ),
                )
            )

        rows.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in rows[:max_items]]

    def get_source_name(self) -> str:
        return "财联社"

    def supports_market(self, ticker: str) -> bool:
        return self.detect_market(ticker) == "a_share"

    def get_supported_source_types(self) -> list[TextSourceType]:
        return [TextSourceType.CLS]
