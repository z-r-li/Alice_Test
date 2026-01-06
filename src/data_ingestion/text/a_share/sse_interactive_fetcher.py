"""
沪市 e互动 问答数据获取器

数据源: 上海证券交易所 e互动平台
API: akshare.stock_sns_sseinfo
适用: .SH 后缀的沪市股票

PRD 价值: key_worry 的直接来源——投资者最关心什么问题
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from ...models import TextItem
from ..base import TextProvider
from ..models import TextSourceType

logger = logging.getLogger("alice_test")


class SSEInteractiveFetcher(TextProvider):
    """
    沪市 e互动 问答数据获取器

    数据源: 上海证券交易所 e互动平台
    API: akshare.stock_sns_sseinfo
    适用: .SH 后缀的沪市股票

    Example:
        >>> fetcher = SSEInteractiveFetcher()
        >>> items = fetcher.fetch_texts(
        ...     ticker="601985.SH",
        ...     name="中国核电",
        ...     lookback_hours=168,
        ...     max_items=5,
        ... )
        >>> print(f"获取到 {len(items)} 条问答")
    """

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        获取沪市股票的互动问答数据

        Args:
            ticker: 股票代码，如 "601985.SH"
            name: 股票名称
            lookback_hours: 回溯时间窗口（小时）
            max_items: 最大返回条目数
            source_types: 可选的数据源类型过滤列表（本实现忽略此参数）

        Returns:
            list[TextItem]: 问答文本列表
        """
        # 检查市场支持
        if not self.supports_market(ticker):
            logger.warning(f"[{ticker}] 非沪市股票，SSEInteractiveFetcher 不支持")
            return []

        # 提取纯代码
        symbol = self.extract_symbol(ticker)

        logger.debug(
            f"[{ticker}] 开始获取上证e互动, lookback={lookback_hours}h, max={max_items}"
        )

        # 调用 AkShare API
        try:
            import akshare as ak

            df = ak.stock_sns_sseinfo(symbol=symbol)
        except Exception as e:
            logger.warning(f"[{ticker}] AkShare 上证e互动获取失败: {e}")
            return []

        if df is None or df.empty:
            logger.debug(f"[{ticker}] 无上证e互动数据")
            return []

        # 转换为 TextItem 列表
        items = self._convert_to_text_items(df, lookback_hours, max_items)

        logger.info(f"[{ticker}] 获取 {len(items)} 条上证e互动问答")
        return items

    def get_source_name(self) -> str:
        """
        获取数据源名称

        Returns:
            str: "上证e互动"
        """
        return "上证e互动"

    def supports_market(self, ticker: str) -> bool:
        """
        判断该 Provider 是否支持指定市场的 ticker

        只支持沪市股票（.SH 后缀）

        Args:
            ticker: 证券代码，如 "601985.SH"

        Returns:
            bool: 是否为沪市股票
        """
        return ticker.upper().endswith(".SH")

    def get_supported_source_types(self) -> list[TextSourceType]:
        """
        返回该 Provider 支持的所有数据源类型

        Returns:
            list[TextSourceType]: [TextSourceType.IRM]
        """
        return [TextSourceType.IRM]

    def _convert_to_text_items(
        self,
        df: pd.DataFrame,
        lookback_hours: int,
        max_items: int,
    ) -> list[TextItem]:
        """
        将上证e互动 DataFrame 转换为 TextItem 列表

        优先返回有回复的问答，按时间倒序排列

        Args:
            df: AkShare 返回的问答 DataFrame
            lookback_hours: 回溯时间（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 过滤后的问答列表
        """
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

        # 分离有回复和无回复的条目
        answered_items: list[tuple[datetime, TextItem]] = []
        unanswered_items: list[tuple[datetime, TextItem]] = []

        for _, row in df.iterrows():
            try:
                # 获取时间字段
                reply_time_str = str(row.get("回复时间", "")).strip()
                question_time_str = str(row.get("提问时间", "")).strip()

                # 判断是否有回复
                answer = str(row.get("答复", "")).strip()
                has_answer = self._has_valid_answer(answer)

                # 确定发布时间：有回复时优先使用回复时间
                if has_answer and reply_time_str:
                    published_at = self._parse_datetime(reply_time_str)
                else:
                    published_at = self._parse_datetime(question_time_str)

                if published_at is None:
                    continue

                # 时间过滤
                if published_at < cutoff_time:
                    continue

                question = str(row.get("问题", "")).strip()
                if not question:
                    continue

                # 构建 TextItem
                item = self._build_qa_text_item(
                    question=question,
                    answer=answer if has_answer else None,
                    published_at=published_at,
                )

                if has_answer:
                    answered_items.append((published_at, item))
                else:
                    unanswered_items.append((published_at, item))

            except Exception as e:
                logger.debug(f"解析上证e互动行失败: {e}")
                continue

        # 按时间倒序排列（最新优先）
        answered_items.sort(key=lambda x: x[0], reverse=True)
        unanswered_items.sort(key=lambda x: x[0], reverse=True)

        # 优先返回有回复的问答
        results = [item for _, item in answered_items] + [
            item for _, item in unanswered_items
        ]
        return results[:max_items]

    def _has_valid_answer(self, answer: str) -> bool:
        """
        判断回答是否有效

        Args:
            answer: 回答内容

        Returns:
            bool: 是否为有效回答
        """
        if not answer:
            return False
        invalid_values = {"", "nan", "-", "暂无回复", "None"}
        return answer not in invalid_values

    def _build_qa_text_item(
        self,
        question: str,
        answer: str | None,
        published_at: datetime,
    ) -> TextItem:
        """
        构建问答 TextItem

        Args:
            question: 投资者问题
            answer: 公司回答（可选）
            published_at: 发布时间

        Returns:
            TextItem: 构建的问答文本项
        """
        # 构建标题
        question_preview = question[:50] + "..." if len(question) > 50 else question
        title = f"[投资者提问] {question_preview}"

        # 构建摘要
        if answer:
            summary = f"问: {question}\n答: {answer}"
        else:
            summary = f"问: {question}\n答: 暂无回复"

        return TextItem(
            source="上证e互动",
            type="news",  # TextItem 暂不支持 irm 类型，使用 news
            title=title,
            summary=summary,
            published_at=published_at,
            url=None,  # e互动无直接链接
        )

    def _parse_datetime(self, date_val) -> datetime | None:
        """
        解析互动易的时间格式 - 兼容 AkShare 返回的多种类型

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
