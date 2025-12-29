"""
A 股机构评级变动获取器

数据源: 东方财富 (stock_institute_recommend_detail)
PRD 价值: implied_growth 变化信号——评级上调/下调反映预期转向
"""

from datetime import datetime, timedelta
import logging

import pandas as pd

from ...models import TextItem
from ..models import FetchResult, TextSourceType

logger = logging.getLogger("alice_test")


class RatingFetcher:
    """
    A 股机构评级变动获取器

    数据源: 东方财富 (stock_institute_recommend_detail)
    PRD 价值: implied_growth 变化信号——评级上调/下调反映预期转向

    Example:
        >>> fetcher = RatingFetcher()
        >>> result = fetcher.fetch(
        ...     ticker="601985.SH",
        ...     symbol="601985",
        ...     name="中国核电",
        ...     lookback_hours=48,
        ...     max_items=10,
        ... )
        >>> print(f"Success: {result.success}, Count: {result.fetch_count}")
    """

    # 评级变动优先级（越高越优先返回）
    CHANGE_PRIORITY = {
        "上调": 3,
        "下调": 3,
        "首次": 2,
        "维持": 1,
    }

    def fetch(
        self,
        ticker: str,
        symbol: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> FetchResult:
        """
        获取机构评级变动

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

        logger.debug(
            f"[{ticker}] 开始获取机构评级, lookback={lookback_hours}h, max={max_items}"
        )

        try:
            df = ak.stock_institute_recommend_detail(symbol=symbol)
        except Exception as e:
            error_msg = f"AkShare 机构评级获取失败: {e}"
            logger.warning(f"[{ticker}] {error_msg}")
            return FetchResult(
                items=[],
                source_type=TextSourceType.RATING,
                success=False,
                error_message=error_msg,
                fetch_count=0,
                request_count=max_items,
            )

        if df is None or df.empty:
            logger.debug(f"[{ticker}] 无机构评级数据")
            return FetchResult(
                items=[],
                source_type=TextSourceType.RATING,
                success=True,
                error_message=None,
                fetch_count=0,
                request_count=max_items,
            )

        # 转换为 TextItem 列表
        items = self._convert_to_text_items(df, lookback_hours, max_items)

        logger.info(f"[{ticker}] 获取 {len(items)} 条机构评级")
        return FetchResult(
            items=items,
            source_type=TextSourceType.RATING,
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
        转换并排序

        排序规则：
        1. 优先返回"上调"和"下调"（变动信号最强）
        2. 其次返回"首次"覆盖
        3. 最后返回"维持"

        Args:
            df: AkShare 返回的机构评级 DataFrame
            lookback_hours: 回溯时间（小时），按天计算
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 过滤并排序后的评级列表
        """
        # 评级日期精度为天，转换为天数后向上取整
        lookback_days = (lookback_hours + 23) // 24
        cutoff_date = datetime.now().date() - timedelta(days=lookback_days)

        # 先过滤时间范围内的记录
        filtered_rows: list[tuple[int, pd.Series, datetime]] = []

        for _, row in df.iterrows():
            try:
                published_at = self._parse_date(row.get("日期", ""))
                if published_at is None:
                    continue

                if published_at.date() < cutoff_date:
                    continue

                # 获取优先级
                change_type = str(row.get("评级变动", ""))
                priority = self.CHANGE_PRIORITY.get(change_type, 0)

                filtered_rows.append((priority, row, published_at))

            except Exception as e:
                logger.debug(f"解析评级行失败: {e}")
                continue

        # 按优先级降序、日期降序排序
        filtered_rows.sort(key=lambda x: (x[0], x[2]), reverse=True)

        # 转换为 TextItem
        results: list[TextItem] = []
        for _, row, published_at in filtered_rows:
            try:
                item = TextItem(
                    source=str(row.get("机构名称", "未知机构")),
                    type="research",
                    title=self._build_title(row),
                    summary=self._build_summary(row),
                    published_at=published_at,
                    url=None,
                )
                results.append(item)

                if len(results) >= max_items:
                    break

            except Exception as e:
                logger.debug(f"构建 TextItem 失败: {e}")
                continue

        return results

    def _parse_date(self, date_str: str) -> datetime | None:
        """
        解析评级的日期格式

        Args:
            date_str: 日期字符串，如 "2024-03-15"

        Returns:
            datetime | None: 解析后的时间（设为当天 00:00:00），解析失败返回 None
        """
        if not date_str:
            return None

        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y%m%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(str(date_str), fmt)
            except ValueError:
                continue

        return None

    def _build_title(self, row: pd.Series) -> str:
        """
        构建标题

        格式: "[{评级变动}] {研报标题}"
        例如: "[上调] 核电景气上行，维持买入"

        Args:
            row: 单行评级数据

        Returns:
            str: 构建的标题
        """
        change_type = str(row.get("评级变动", ""))
        report_title = str(row.get("研报标题", ""))

        if change_type and report_title:
            return f"[{change_type}] {report_title}"
        elif change_type:
            rating = str(row.get("评级", ""))
            return f"[{change_type}] {rating}" if rating else f"[{change_type}]"
        elif report_title:
            return report_title
        else:
            return "机构评级"

    def _build_summary(self, row: pd.Series) -> str:
        """
        构建摘要

        格式: "评级: {评级} | 机构: {机构名称} | 目标价: {目标价}"

        Args:
            row: 单行评级数据

        Returns:
            str: 构建的摘要文本
        """
        parts = []

        # 评级信息
        rating = row.get("评级", "")
        if rating and str(rating) not in ["", "nan", "-"]:
            parts.append(f"评级: {rating}")

        # 机构名称
        institution = row.get("机构名称", "")
        if institution and str(institution) not in ["", "nan", "-"]:
            parts.append(f"机构: {institution}")

        # 分析师
        analyst = row.get("分析师", "")
        if analyst and str(analyst) not in ["", "nan", "-"]:
            parts.append(f"分析师: {analyst}")

        # 目标价
        target_price = row.get("目标价", "")
        if target_price and str(target_price) not in ["", "nan", "-", "None"]:
            try:
                price_float = float(target_price)
                parts.append(f"目标价: {price_float:.2f}")
            except (ValueError, TypeError):
                # 目标价可能是区间，如 "10.00-12.00"
                parts.append(f"目标价: {target_price}")

        return " | ".join(parts) if parts else "无摘要信息"
