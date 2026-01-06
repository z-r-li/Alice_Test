"""
AkShare 新闻获取器
接口: stock_news_em
数据源: 东方财富
"""
from datetime import datetime, timedelta
from typing import List
import logging

from ...models import TextItem

logger = logging.getLogger("alice_test")


class AkShareNewsFetcher:
    """AkShare A股新闻获取器"""

    def __init__(self, max_retries: int = 2):
        self._max_retries = max_retries

    def fetch(
        self,
        symbol: str,
        lookback_hours: int = 48,
        max_items: int = 20,
    ) -> List[TextItem]:
        """
        获取个股新闻

        Args:
            symbol: 股票代码（不带后缀），如 "601985"
            lookback_hours: 回溯小时数
            max_items: 最大返回条数

        Returns:
            List[TextItem]: 新闻列表
        """
        import akshare as ak

        try:
            df = ak.stock_news_em(symbol=symbol)
        except Exception as e:
            logger.warning(f"[{symbol}] AkShare 新闻获取失败: {e}")
            return []

        if df is None or df.empty:
            logger.debug(f"[{symbol}] 无新闻数据")
            return []

        # 时间过滤
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
        results: List[TextItem] = []

        for _, row in df.iterrows():
            try:
                # 解析发布时间
                published_at = self._parse_datetime(row.get("发布时间", ""))
                if published_at is None or published_at < cutoff_time:
                    continue

                # 构建 TextItem
                item = TextItem(
                    source=str(row.get("文章来源", "东方财富")),
                    type="news",
                    title=str(row.get("新闻标题", "")),
                    summary=self._truncate_content(str(row.get("新闻内容", "")), 500),
                    published_at=published_at,
                    url=str(row.get("新闻链接", None)) or None,
                )
                results.append(item)

                if len(results) >= max_items:
                    break

            except Exception as e:
                logger.debug(f"[{symbol}] 解析新闻行失败: {e}")
                continue

        logger.info(f"[{symbol}] 获取 {len(results)} 条新闻")
        return results

    def _parse_datetime(self, date_val) -> datetime | None:
        """
        解析时间字段 - 兼容 AkShare 返回的多种类型

        支持:
        - datetime.datetime 对象
        - datetime.date 对象 (转为当天 00:00:00)
        - str 字符串 (多种格式)
        - pandas.Timestamp

        Args:
            date_val: 时间值，可以是多种类型

        Returns:
            datetime | None: 解析后的时间，解析失败返回 None
        """
        import pandas as pd
        from datetime import date

        if date_val is None:
            return None

        # 1. 已经是 datetime 对象
        if isinstance(date_val, datetime):
            return date_val

        # 2. date 对象 (但不是 datetime) - 转为当天 00:00:00
        if isinstance(date_val, date):
            return datetime.combine(date_val, datetime.min.time())

        # 3. pandas Timestamp
        if isinstance(date_val, pd.Timestamp):
            return date_val.to_pydatetime()

        # 4. 字符串 - 尝试多种格式解析
        if isinstance(date_val, str):
            date_str = date_val.strip()
            if not date_str or date_str in ("nan", "None", "-", ""):
                return None

            formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d",
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue

        # 5. 其他类型尝试转字符串后解析
        try:
            date_str = str(date_val).strip()
            if date_str and date_str not in ("nan", "None", "-", ""):
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass

        return None

    def _truncate_content(self, content: str, max_len: int) -> str:
        """截断内容"""
        content = content.strip()
        if len(content) <= max_len:
            return content
        return content[:max_len] + "..."
