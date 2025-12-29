"""
A 股互动易问答获取器

根据 ticker 后缀自动选择数据源:
- .SH -> 上证e互动 (stock_sns_sseinfo)
- .SZ -> 巨潮互动易 (stock_irm_cninfo + stock_irm_ans_cninfo)

PRD 价值: key_worry 的直接来源——投资者最关心什么问题
"""

from datetime import datetime, timedelta
import logging

import pandas as pd

from ...models import TextItem
from ..models import FetchResult, TextSourceType

logger = logging.getLogger("alice_test")


class IRMFetcher:
    """
    A 股互动易问答获取器

    根据 ticker 后缀自动选择：
    - .SH -> 上证e互动 (stock_sns_sseinfo)
    - .SZ -> 巨潮互动易 (stock_irm_cninfo + stock_irm_ans_cninfo)

    PRD 价值: key_worry 的直接来源——投资者最关心什么问题

    Example:
        >>> fetcher = IRMFetcher()
        >>> result = fetcher.fetch(
        ...     ticker="601985.SH",
        ...     symbol="601985",
        ...     name="中国核电",
        ...     lookback_hours=168,
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
        获取互动易问答

        Args:
            ticker: 完整代码如 "601985.SH"
            symbol: 纯数字代码如 "601985"
            name: 股票名称
            lookback_hours: 时间窗口（小时）
            max_items: 最大返回条数

        Returns:
            FetchResult: 包含 TextItem 列表和元信息
        """
        if ticker.upper().endswith(".SH"):
            return self._fetch_sse(symbol, lookback_hours, max_items)
        else:
            return self._fetch_szse(symbol, lookback_hours, max_items)

    def _fetch_sse(
        self,
        symbol: str,
        lookback_hours: int,
        max_items: int,
    ) -> FetchResult:
        """
        沪市：上证e互动

        使用 akshare.stock_sns_sseinfo 获取问答数据
        返回字段: 提问时间, 问题, 回复时间, 答复
        """
        import akshare as ak

        logger.debug(f"[{symbol}.SH] 开始获取上证e互动, lookback={lookback_hours}h, max={max_items}")

        try:
            df = ak.stock_sns_sseinfo(symbol=symbol)
        except Exception as e:
            error_msg = f"AkShare 上证e互动获取失败: {e}"
            logger.warning(f"[{symbol}.SH] {error_msg}")
            return FetchResult(
                items=[],
                source_type=TextSourceType.IRM,
                success=False,
                error_message=error_msg,
                fetch_count=0,
                request_count=max_items,
            )

        if df is None or df.empty:
            logger.debug(f"[{symbol}.SH] 无上证e互动数据")
            return FetchResult(
                items=[],
                source_type=TextSourceType.IRM,
                success=True,
                error_message=None,
                fetch_count=0,
                request_count=max_items,
            )

        # 转换为 TextItem 列表
        items = self._convert_sse_to_text_items(df, lookback_hours, max_items)

        logger.info(f"[{symbol}.SH] 获取 {len(items)} 条上证e互动问答")
        return FetchResult(
            items=items,
            source_type=TextSourceType.IRM,
            success=True,
            error_message=None,
            fetch_count=len(items),
            request_count=max_items,
        )

    def _fetch_szse(
        self,
        symbol: str,
        lookback_hours: int,
        max_items: int,
    ) -> FetchResult:
        """
        深市：巨潮互动易

        使用 akshare.stock_irm_cninfo 获取提问
        使用 akshare.stock_irm_ans_cninfo 获取回答
        然后合并匹配问答对
        """
        import akshare as ak

        logger.debug(f"[{symbol}.SZ] 开始获取巨潮互动易, lookback={lookback_hours}h, max={max_items}")

        # 获取问题和回答数据
        df_questions = None
        df_answers = None

        try:
            df_questions = ak.stock_irm_cninfo(symbol=symbol)
        except Exception as e:
            logger.warning(f"[{symbol}.SZ] 获取巨潮互动易问题失败: {e}")

        try:
            df_answers = ak.stock_irm_ans_cninfo(symbol=symbol)
        except Exception as e:
            logger.warning(f"[{symbol}.SZ] 获取巨潮互动易回答失败: {e}")

        # 如果两个都失败，返回错误
        if (df_questions is None or df_questions.empty) and (df_answers is None or df_answers.empty):
            logger.debug(f"[{symbol}.SZ] 无巨潮互动易数据")
            return FetchResult(
                items=[],
                source_type=TextSourceType.IRM,
                success=True,
                error_message=None,
                fetch_count=0,
                request_count=max_items,
            )

        # 转换为 TextItem 列表
        items = self._convert_szse_to_text_items(
            df_questions, df_answers, lookback_hours, max_items
        )

        logger.info(f"[{symbol}.SZ] 获取 {len(items)} 条巨潮互动易问答")
        return FetchResult(
            items=items,
            source_type=TextSourceType.IRM,
            success=True,
            error_message=None,
            fetch_count=len(items),
            request_count=max_items,
        )

    def _convert_sse_to_text_items(
        self,
        df: pd.DataFrame,
        lookback_hours: int,
        max_items: int,
    ) -> list[TextItem]:
        """
        将上证e互动 DataFrame 转换为 TextItem 列表

        优先返回有回复的问答

        Args:
            df: AkShare 返回的问答 DataFrame
            lookback_hours: 回溯时间（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 过滤后的问答列表
        """
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

        # 分离有回复和无回复的条目
        answered_items: list[TextItem] = []
        unanswered_items: list[TextItem] = []

        for _, row in df.iterrows():
            try:
                # 优先使用回复时间，如果没有则使用提问时间
                reply_time_str = row.get("回复时间", "")
                question_time_str = row.get("提问时间", "")

                # 判断是否有回复
                answer = str(row.get("答复", "")).strip()
                has_answer = bool(answer) and answer not in ["", "nan", "-", "暂无回复"]

                # 确定发布时间
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
                    source="上证e互动",
                    published_at=published_at,
                )

                if has_answer:
                    answered_items.append(item)
                else:
                    unanswered_items.append(item)

            except Exception as e:
                logger.debug(f"解析上证e互动行失败: {e}")
                continue

        # 优先返回有回复的问答
        results = answered_items + unanswered_items
        return results[:max_items]

    def _convert_szse_to_text_items(
        self,
        df_questions: pd.DataFrame | None,
        df_answers: pd.DataFrame | None,
        lookback_hours: int,
        max_items: int,
    ) -> list[TextItem]:
        """
        将巨潮互动易 DataFrame 转换为 TextItem 列表

        优先返回有回复的问答，并按关注数排序

        Args:
            df_questions: 问题 DataFrame (提问日期, 问题内容, 提问者, 关注数)
            df_answers: 回答 DataFrame (回答日期, 问题内容, 回答内容, 回答者)
            lookback_hours: 回溯时间（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 过滤后的问答列表
        """
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

        # 构建问题到回答的映射
        answer_map: dict[str, tuple[str, datetime | None]] = {}
        if df_answers is not None and not df_answers.empty:
            for _, row in df_answers.iterrows():
                question_content = str(row.get("问题内容", "")).strip()
                answer_content = str(row.get("回答内容", "")).strip()
                answer_date_str = str(row.get("回答日期", ""))
                answer_date = self._parse_datetime(answer_date_str)

                if question_content and answer_content:
                    answer_map[question_content] = (answer_content, answer_date)

        # 处理问题列表
        answered_items: list[tuple[int, TextItem]] = []  # (关注数, item)
        unanswered_items: list[tuple[int, TextItem]] = []

        if df_questions is not None and not df_questions.empty:
            for _, row in df_questions.iterrows():
                try:
                    question_content = str(row.get("问题内容", "")).strip()
                    if not question_content:
                        continue

                    # 解析日期
                    question_date_str = str(row.get("提问日期", ""))
                    question_date = self._parse_datetime(question_date_str)

                    # 检查是否有回答
                    answer_info = answer_map.get(question_content)
                    has_answer = answer_info is not None

                    # 确定发布时间
                    if has_answer and answer_info[1] is not None:
                        published_at = answer_info[1]
                    elif question_date is not None:
                        published_at = question_date
                    else:
                        continue

                    # 时间过滤
                    if published_at < cutoff_time:
                        continue

                    # 获取关注数
                    attention = 0
                    attention_val = row.get("关注数", 0)
                    if attention_val and str(attention_val) not in ["", "nan", "-"]:
                        try:
                            attention = int(float(attention_val))
                        except (ValueError, TypeError):
                            attention = 0

                    # 构建 TextItem
                    answer = answer_info[0] if has_answer else None
                    item = self._build_qa_text_item(
                        question=question_content,
                        answer=answer,
                        source="巨潮互动易",
                        published_at=published_at,
                    )

                    if has_answer:
                        answered_items.append((attention, item))
                    else:
                        unanswered_items.append((attention, item))

                except Exception as e:
                    logger.debug(f"解析巨潮互动易行失败: {e}")
                    continue

        # 按关注数排序（高关注数优先）
        answered_items.sort(key=lambda x: x[0], reverse=True)
        unanswered_items.sort(key=lambda x: x[0], reverse=True)

        # 优先返回有回复的问答
        results = [item for _, item in answered_items] + [item for _, item in unanswered_items]
        return results[:max_items]

    def _build_qa_text_item(
        self,
        question: str,
        answer: str | None,
        source: str,
        published_at: datetime,
    ) -> TextItem:
        """
        构建问答 TextItem

        title: "[投资者提问] {问题前50字}..."
        summary: "公司回复: {回答前200字}" 或 "暂无回复"

        Args:
            question: 投资者问题
            answer: 公司回答（可选）
            source: 数据来源（上证e互动/巨潮互动易）
            published_at: 发布时间

        Returns:
            TextItem: 构建的问答文本项
        """
        # 构建标题
        question_preview = question[:50] + "..." if len(question) > 50 else question
        title = f"[投资者提问] {question_preview}"

        # 构建摘要
        if answer:
            answer_preview = answer[:200] + "..." if len(answer) > 200 else answer
            summary = f"公司回复: {answer_preview}"
        else:
            summary = "暂无回复"

        return TextItem(
            source=source,
            type="news",  # TextItem 暂不支持 irm 类型，使用 news
            title=title,
            summary=summary,
            published_at=published_at,
            url=None,
        )

    def _parse_datetime(self, date_str: str) -> datetime | None:
        """
        解析互动易的时间格式

        Args:
            date_str: 时间字符串

        Returns:
            datetime | None: 解析后的时间，解析失败返回 None
        """
        if not date_str:
            return None

        date_str = str(date_str).strip()
        if not date_str or date_str in ["nan", "None", "-"]:
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

        return None
