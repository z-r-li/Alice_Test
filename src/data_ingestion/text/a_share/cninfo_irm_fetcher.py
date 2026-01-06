"""
深市互动易问答数据获取器

数据源: 巨潮资讯-互动易
API:
  - akshare.stock_irm_cninfo (投资者提问)
  - akshare.stock_irm_ans_cninfo (公司回答)
适用: .SZ 后缀的深市股票

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


class CNInfoIRMFetcher(TextProvider):
    """
    深市互动易问答数据获取器

    数据源: 巨潮资讯-互动易
    API:
      - akshare.stock_irm_cninfo (投资者提问)
      - akshare.stock_irm_ans_cninfo (公司回答)
    适用: .SZ 后缀的深市股票

    Example:
        >>> fetcher = CNInfoIRMFetcher()
        >>> items = fetcher.fetch_texts(
        ...     ticker="000001.SZ",
        ...     name="平安银行",
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
        获取深市股票的互动易问答数据

        Args:
            ticker: 股票代码，如 "000001.SZ"
            name: 股票名称
            lookback_hours: 回溯时间窗口（小时）
            max_items: 最大返回条目数
            source_types: 可选的数据源类型过滤列表（本实现忽略此参数）

        Returns:
            list[TextItem]: 问答文本列表
        """
        # 检查市场支持
        if not self.supports_market(ticker):
            logger.warning(f"[{ticker}] 非深市股票，CNInfoIRMFetcher 不支持")
            return []

        # 提取纯代码（去掉 .SZ 后缀）
        symbol = self.extract_symbol(ticker)

        logger.debug(
            f"[{ticker}] 开始获取巨潮互动易, lookback={lookback_hours}h, max={max_items}"
        )

        # 获取问题和回答数据
        questions_df = self._fetch_questions(symbol)
        answers_df = self._fetch_answers(symbol)

        # 如果两个都失败或为空，返回空列表
        if (questions_df is None or questions_df.empty) and (
            answers_df is None or answers_df.empty
        ):
            logger.debug(f"[{ticker}] 无巨潮互动易数据")
            return []

        # 合并问答数据
        merged_qa = self._merge_qa(questions_df, answers_df)

        # 转换为 TextItem 列表并过滤排序
        items = self._convert_to_text_items(merged_qa, lookback_hours, max_items)

        logger.info(f"[{ticker}] 获取 {len(items)} 条巨潮互动易问答")
        return items

    def get_source_name(self) -> str:
        """
        获取数据源名称

        Returns:
            str: "巨潮互动易"
        """
        return "巨潮互动易"

    def supports_market(self, ticker: str) -> bool:
        """
        判断该 Provider 是否支持指定市场的 ticker

        只支持深市股票（.SZ 后缀）

        Args:
            ticker: 证券代码，如 "000001.SZ"

        Returns:
            bool: 是否为深市股票
        """
        return ticker.upper().endswith(".SZ")

    def get_supported_source_types(self) -> list[TextSourceType]:
        """
        返回该 Provider 支持的所有数据源类型

        Returns:
            list[TextSourceType]: [TextSourceType.IRM]
        """
        return [TextSourceType.IRM]

    def _fetch_questions(self, symbol: str) -> pd.DataFrame | None:
        """
        获取投资者提问

        Args:
            symbol: 纯数字股票代码，如 "000001"

        Returns:
            pd.DataFrame | None: 问题数据，失败时返回 None
        """
        try:
            import akshare as ak

            df = ak.stock_irm_cninfo(symbol=symbol)
            return df
        except Exception as e:
            logger.warning(f"[{symbol}.SZ] 获取巨潮互动易问题失败: {e}")
            return None

    def _fetch_answers(self, symbol: str) -> pd.DataFrame | None:
        """
        获取公司回答

        Args:
            symbol: 纯数字股票代码，如 "000001"

        Returns:
            pd.DataFrame | None: 回答数据，失败时返回 None
        """
        try:
            import akshare as ak

            df = ak.stock_irm_ans_cninfo(symbol=symbol)
            return df
        except Exception as e:
            logger.warning(f"[{symbol}.SZ] 获取巨潮互动易回答失败: {e}")
            return None

    def _merge_qa(
        self,
        questions_df: pd.DataFrame | None,
        answers_df: pd.DataFrame | None,
    ) -> list[dict]:
        """
        合并问答数据

        策略：
        1. 以问题内容为 key 匹配回答
        2. 有回答的问题优先级更高
        3. 使用回答时间作为最终时间戳

        Args:
            questions_df: 问题 DataFrame (提问日期, 问题内容, 提问者, 关注数)
            answers_df: 回答 DataFrame (回答日期, 问题内容, 回答内容, 回答者)

        Returns:
            list[dict]: 合并后的问答数据列表
        """
        # 构建问题到回答的映射
        answer_map: dict[str, dict] = {}
        if answers_df is not None and not answers_df.empty:
            for _, row in answers_df.iterrows():
                question_key = str(row.get("问题内容", "")).strip()
                if not question_key:
                    continue

                answer_content = str(row.get("回答内容", "")).strip()
                answer_date_str = str(row.get("回答日期", ""))
                responder = str(row.get("回答者", "")).strip()

                answer_map[question_key] = {
                    "answer": answer_content,
                    "answer_date": answer_date_str,
                    "responder": responder,
                }

        # 遍历问题，匹配回答
        merged_items: list[dict] = []

        if questions_df is not None and not questions_df.empty:
            for _, q_row in questions_df.iterrows():
                question = str(q_row.get("问题内容", "")).strip()
                if not question:
                    continue

                question_date_str = str(q_row.get("提问日期", ""))
                asker = str(q_row.get("提问者", "")).strip()

                # 获取关注数
                attention = 0
                attention_val = q_row.get("关注数", 0)
                if attention_val and str(attention_val) not in ("", "nan", "-"):
                    try:
                        attention = int(float(attention_val))
                    except (ValueError, TypeError):
                        attention = 0

                # 检查是否有回答
                answer_info = answer_map.get(question)

                merged_items.append(
                    {
                        "question": question,
                        "question_date": question_date_str,
                        "asker": asker,
                        "attention": attention,
                        "answer": answer_info["answer"] if answer_info else None,
                        "answer_date": answer_info["answer_date"] if answer_info else None,
                        "responder": answer_info["responder"] if answer_info else None,
                        "has_answer": answer_info is not None,
                    }
                )

        return merged_items

    def _convert_to_text_items(
        self,
        merged_qa: list[dict],
        lookback_hours: int,
        max_items: int,
    ) -> list[TextItem]:
        """
        将合并后的问答数据转换为 TextItem 列表

        排序策略：
        1. 有回答 > 无回答
        2. 关注数高 > 关注数低
        3. 时间近 > 时间远

        Args:
            merged_qa: 合并后的问答数据列表
            lookback_hours: 回溯时间（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 过滤并排序后的问答列表
        """
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

        # 分离有回复和无回复的条目
        answered_items: list[tuple[int, datetime, TextItem]] = []  # (attention, time, item)
        unanswered_items: list[tuple[int, datetime, TextItem]] = []

        for qa in merged_qa:
            try:
                # 确定发布时间：有回复时优先使用回复时间
                if qa["has_answer"] and qa["answer_date"]:
                    published_at = self._parse_datetime(qa["answer_date"])
                else:
                    published_at = self._parse_datetime(qa["question_date"])

                if published_at is None:
                    continue

                # 时间过滤
                if published_at < cutoff_time:
                    continue

                # 构建 TextItem
                item = self._build_qa_text_item(
                    question=qa["question"],
                    answer=qa["answer"],
                    responder=qa["responder"],
                    has_answer=qa["has_answer"],
                    published_at=published_at,
                )

                attention = qa["attention"]

                if qa["has_answer"]:
                    answered_items.append((attention, published_at, item))
                else:
                    unanswered_items.append((attention, published_at, item))

            except Exception as e:
                logger.debug(f"解析巨潮互动易问答失败: {e}")
                continue

        # 按关注数和时间排序（高关注数优先，时间近优先）
        answered_items.sort(key=lambda x: (x[0], x[1]), reverse=True)
        unanswered_items.sort(key=lambda x: (x[0], x[1]), reverse=True)

        # 优先返回有回复的问答
        results = [item for _, _, item in answered_items] + [
            item for _, _, item in unanswered_items
        ]
        return results[:max_items]

    def _build_qa_text_item(
        self,
        question: str,
        answer: str | None,
        responder: str | None,
        has_answer: bool,
        published_at: datetime,
    ) -> TextItem:
        """
        构建问答 TextItem

        Args:
            question: 投资者问题
            answer: 公司回答（可选）
            responder: 回答者（董秘/证代等）
            has_answer: 是否有回答
            published_at: 发布时间

        Returns:
            TextItem: 构建的问答文本项
        """
        # 构建标题
        status_tag = "已回复" if has_answer else "待回复"
        question_preview = question[:40] + "..." if len(question) > 40 else question
        title = f"[{status_tag}] {question_preview}"

        # 构建摘要
        summary = self._build_qa_summary(question, answer, responder)

        return TextItem(
            source="巨潮互动易",
            type="news",  # TextItem 暂不支持 irm 类型，使用 news
            title=title,
            summary=summary,
            published_at=published_at,
            url=None,  # 巨潮互动易无直接链接
        )

    def _build_qa_summary(
        self,
        question: str,
        answer: str | None,
        responder: str | None,
    ) -> str:
        """
        构建问答摘要文本

        Args:
            question: 投资者问题
            answer: 公司回答（可选）
            responder: 回答者（可选）

        Returns:
            str: 格式化的问答摘要
        """
        if answer:
            responder_tag = f"({responder})" if responder else ""
            return f"问: {question}\n答{responder_tag}: {answer}"
        return f"问: {question}\n[尚未回复]"

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
