"""
A 股研报获取器

数据源: 东方财富研报中心 (stock_research_report_em)
PRD 价值: 机构观点来源；implied_growth 推算依据
"""

from datetime import datetime, timedelta
import logging

import pandas as pd

from ...models import TextItem
from ..models import FetchResult, TextSourceType

logger = logging.getLogger("alice_test")


class ResearchFetcher:
    """
    A 股研报获取器

    数据源: 东方财富研报中心 (stock_research_report_em)
    PRD 价值: 机构观点来源；implied_growth 推算依据

    Example:
        >>> fetcher = ResearchFetcher()
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
        获取个股研报

        Args:
            ticker: 完整代码如 "601985.SH"
            symbol: 纯数字代码如 "601985"
            name: 股票名称
            lookback_hours: 时间窗口（小时），按天计算
            max_items: 最大返回条数

        Returns:
            FetchResult: 包含 TextItem 列表和元信息
        """
        import akshare as ak

        logger.debug(f"[{ticker}] 开始获取研报, lookback={lookback_hours}h, max={max_items}")

        try:
            df = ak.stock_research_report_em(symbol=symbol)
        except Exception as e:
            error_msg = f"AkShare 研报获取失败: {e}"
            logger.warning(f"[{ticker}] {error_msg}")
            return FetchResult(
                items=[],
                source_type=TextSourceType.RESEARCH,
                success=False,
                error_message=error_msg,
                fetch_count=0,
                request_count=max_items,
            )

        if df is None or df.empty:
            logger.debug(f"[{ticker}] 无研报数据")
            return FetchResult(
                items=[],
                source_type=TextSourceType.RESEARCH,
                success=True,
                error_message=None,
                fetch_count=0,
                request_count=max_items,
            )

        # 转换为 TextItem 列表
        items = self._convert_to_text_items(df, lookback_hours, max_items)

        logger.info(f"[{ticker}] 获取 {len(items)} 条研报")
        return FetchResult(
            items=items,
            source_type=TextSourceType.RESEARCH,
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
            df: AkShare 返回的研报 DataFrame
            lookback_hours: 回溯时间（小时），按天计算
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 过滤后的研报列表
        """
        # 研报日期精度为天，转换为天数后向上取整
        lookback_days = (lookback_hours + 23) // 24  # 向上取整
        cutoff_date = datetime.now().date() - timedelta(days=lookback_days)
        results: list[TextItem] = []

        for _, row in df.iterrows():
            try:
                # 解析发布日期
                published_at = self._parse_date(row.get("日期", ""))
                if published_at is None:
                    continue

                # 按天过滤（研报只有日期）
                if published_at.date() < cutoff_date:
                    continue

                # 构建 TextItem
                # 列名映射: AkShare stock_research_report_em 返回的列名
                # - 报告名称 (报告标题)
                # - 机构 (机构名称)
                # - 报告PDF链接 (研报链接)
                title = str(row.get("报告名称", "") or row.get("报告标题", "")).strip()
                if not title:
                    logger.debug("跳过空标题研报")
                    continue

                source = str(row.get("机构", "") or row.get("机构名称", "") or "未知机构")
                url_val = row.get("报告PDF链接", "") or row.get("研报链接", "")
                url = str(url_val).strip() if url_val else None

                item = TextItem(
                    source=source,
                    type="research",
                    title=title,
                    summary=self._build_summary(row),
                    published_at=published_at,
                    url=url,
                )
                results.append(item)

                if len(results) >= max_items:
                    break

            except Exception as e:
                logger.debug(f"解析研报行失败: {e}")
                continue

        return results

    def _parse_date(self, date_val) -> datetime | None:
        """
        解析研报的日期格式 - 兼容 AkShare 返回的多种类型

        支持:
        - datetime.datetime 对象
        - datetime.date 对象 (转为当天 00:00:00)
        - str 字符串 (多种格式)
        - pandas.Timestamp

        Args:
            date_val: 日期值，可以是多种类型

        Returns:
            datetime | None: 解析后的时间（设为当天 00:00:00），解析失败返回 None
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
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%Y%m%d",
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
                return datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            pass

        return None

    def _build_summary(self, row: pd.Series) -> str:
        """
        构建研报摘要

        格式: "评级: {东财评级} | 机构: {机构} | 分析师: {研究员}"
        如有 EPS 预测，追加: "| 2025E EPS: {value}"

        Args:
            row: 单行研报数据

        Returns:
            str: 构建的摘要文本
        """
        parts = []

        # 评级信息
        rating = row.get("东财评级", "")
        if rating and str(rating) not in ["", "nan", "-"]:
            parts.append(f"评级: {rating}")

        # 机构名称 (兼容两种列名)
        institution = row.get("机构", "") or row.get("机构名称", "")
        if institution and str(institution) not in ["", "nan", "-"]:
            parts.append(f"机构: {institution}")

        # 分析师 (可选字段)
        analyst = row.get("研究员", "")
        if analyst and str(analyst) not in ["", "nan", "-"]:
            parts.append(f"分析师: {analyst}")

        # EPS 预测 - 兼容新旧两种列名格式
        # 新格式: "2025-盈利预测-收益", "2026-盈利预测-收益", "2027-盈利预测-收益"
        # 旧格式: "2024E EPS", "2025E EPS", "2026E EPS"
        eps_fields = [
            ("2025-盈利预测-收益", "2025E EPS"),
            ("2026-盈利预测-收益", "2026E EPS"),
            ("2027-盈利预测-收益", "2027E EPS"),
            ("2024E EPS", "2024E EPS"),
            ("2025E EPS", "2025E EPS"),
            ("2026E EPS", "2026E EPS"),
        ]

        seen_years = set()
        for field_name, display_name in eps_fields:
            year = display_name[:4]  # 提取年份
            if year in seen_years:
                continue
            eps_value = row.get(field_name, "")
            if eps_value and str(eps_value) not in ["", "nan", "-"]:
                try:
                    eps_float = float(eps_value)
                    parts.append(f"{display_name}: {eps_float:.2f}")
                    seen_years.add(year)
                except (ValueError, TypeError):
                    pass

        return " | ".join(parts) if parts else "无摘要信息"
