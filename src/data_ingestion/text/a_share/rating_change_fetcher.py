"""
机构评级变动数据获取器

数据源: 东方财富
API: akshare.stock_institute_recommend_detail
用途: 捕捉机构预期变化信号

PRD 价值: implied_growth 变化信号——评级上调/下调反映预期转向
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from ...models import TextItem
from ..base import TextProvider
from ..models import TextSourceType

logger = logging.getLogger("alice_test")


class RatingChangeFetcher(TextProvider):
    """
    机构评级变动数据获取器

    数据源: 东方财富
    API: akshare.stock_institute_recommend_detail
    用途: 捕捉机构预期变化信号

    Example:
        >>> fetcher = RatingChangeFetcher()
        >>> items = fetcher.fetch_texts(
        ...     ticker="601985.SH",
        ...     name="中国核电",
        ...     lookback_hours=48,
        ...     max_items=10,
        ... )
        >>> print(f"获取到 {len(items)} 条评级变动")
    """

    # 评级变动优先级（越高越优先返回）
    CHANGE_PRIORITY = {
        "上调": 3,
        "下调": 3,
        "首次": 2,
        "维持": 1,
    }

    # 评级变动对应的 emoji
    CHANGE_EMOJI = {
        "上调": "📈",
        "下调": "📉",
        "维持": "➡️",
        "首次": "🆕",
    }

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        获取机构评级变动数据

        重点关注：
        - 评级上调 → 市场预期改善信号
        - 评级下调 → 市场预期恶化信号
        - 首次评级 → 新增机构关注

        Args:
            ticker: 股票代码，如 "601985.SH"
            name: 股票名称
            lookback_hours: 回溯时间窗口（小时）
            max_items: 最大返回条目数
            source_types: 可选的数据源类型过滤列表（本实现忽略此参数）

        Returns:
            list[TextItem]: 评级变动文本列表
        """
        # 检查市场支持
        if not self.supports_market(ticker):
            logger.warning(f"[{ticker}] 非 A 股，RatingChangeFetcher 不支持")
            return []

        # 提取纯代码
        symbol = self.extract_symbol(ticker)

        logger.debug(
            f"[{ticker}] 开始获取机构评级变动, lookback={lookback_hours}h, max={max_items}"
        )

        try:
            import akshare as ak

            df = ak.stock_institute_recommend_detail(symbol=symbol)
        except Exception as e:
            error_msg = f"AkShare 机构评级变动获取失败: {e}"
            logger.warning(f"[{ticker}] {error_msg}")
            return []

        if df is None or df.empty:
            logger.debug(f"[{ticker}] 无机构评级变动数据")
            return []

        # 转换为 TextItem 列表
        items = self._convert_to_text_items(df, lookback_hours, max_items)

        logger.info(f"[{ticker}] 获取 {len(items)} 条机构评级变动")
        return items

    def get_source_name(self) -> str:
        """
        获取数据源名称

        Returns:
            str: "东方财富机构评级"
        """
        return "东方财富机构评级"

    def supports_market(self, ticker: str) -> bool:
        """
        判断该 Provider 是否支持指定市场的 ticker

        只支持 A 股（.SH 或 .SZ 后缀）

        Args:
            ticker: 证券代码，如 "601985.SH"

        Returns:
            bool: 是否为 A 股
        """
        return self.detect_market(ticker) == "a_share"

    def get_supported_source_types(self) -> list[TextSourceType]:
        """
        返回该 Provider 支持的所有数据源类型

        Returns:
            list[TextSourceType]: [TextSourceType.RATING]
        """
        return [TextSourceType.RATING]

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
                    summary=self._build_rating_summary(row),
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

        date_str = str(date_str).strip()
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

        return None

    def _build_title(self, row: pd.Series) -> str:
        """
        构建标题

        格式: "{emoji}[{评级变动}→{评级}] {研报标题}"
        例如: "📈[上调→买入] 核电景气上行"

        Args:
            row: 单行评级数据

        Returns:
            str: 构建的标题
        """
        change_type = str(row.get("评级变动", ""))
        rating = str(row.get("评级", ""))
        report_title = str(row.get("研报标题", ""))

        # 获取 emoji
        emoji = self.CHANGE_EMOJI.get(change_type, "")

        # 构建评级变动部分
        if change_type and rating:
            change_part = f"[{change_type}→{rating}]"
        elif change_type:
            change_part = f"[{change_type}]"
        elif rating:
            change_part = f"[{rating}]"
        else:
            change_part = ""

        # 拼接最终标题
        if emoji and change_part and report_title:
            return f"{emoji}{change_part} {report_title}"
        elif emoji and change_part:
            return f"{emoji}{change_part}"
        elif report_title:
            return report_title
        else:
            return "机构评级"

    def _build_rating_summary(self, row: pd.Series) -> str:
        """
        构建摘要

        格式: "机构: {机构名称} | 分析师: {分析师} | 评级: {评级} | 变动: {评级变动}"

        Args:
            row: 单行评级数据

        Returns:
            str: 构建的摘要文本
        """
        parts = []

        # 机构名称
        institution = row.get("机构名称", "")
        if institution and str(institution) not in ("", "nan", "-"):
            parts.append(f"机构: {institution}")

        # 分析师
        analyst = row.get("分析师", "")
        if analyst and str(analyst) not in ("", "nan", "-"):
            parts.append(f"分析师: {analyst}")

        # 评级信息
        rating = row.get("评级", "")
        if rating and str(rating) not in ("", "nan", "-"):
            parts.append(f"评级: {rating}")

        # 评级变动
        change_type = row.get("评级变动", "")
        if change_type and str(change_type) not in ("", "nan", "-"):
            parts.append(f"变动: {change_type}")

        # 目标价
        target_price = row.get("目标价", "")
        if target_price and str(target_price) not in ("", "nan", "-", "None"):
            try:
                price_float = float(target_price)
                parts.append(f"目标价: {price_float:.2f}")
            except (ValueError, TypeError):
                # 目标价可能是区间，如 "10.00-12.00"
                parts.append(f"目标价: {target_price}")

        return " | ".join(parts) if parts else "无摘要信息"

    def _calculate_rating_trend(self, df: pd.DataFrame) -> dict:
        """
        计算评级趋势统计

        Args:
            df: AkShare 返回的机构评级 DataFrame

        Returns:
            dict: {
                "upgrades": 上调数量,
                "downgrades": 下调数量,
                "maintains": 维持数量,
                "initiations": 首次评级数量,
                "trend_signal": 趋势信号 ("bullish"/"bearish"/"neutral")
            }
        """
        if df is None or df.empty:
            return {
                "upgrades": 0,
                "downgrades": 0,
                "maintains": 0,
                "initiations": 0,
                "trend_signal": "neutral",
            }

        # 统计各类评级变动数量
        change_counts = df["评级变动"].value_counts()

        upgrades = int(change_counts.get("上调", 0))
        downgrades = int(change_counts.get("下调", 0))
        maintains = int(change_counts.get("维持", 0))
        initiations = int(change_counts.get("首次", 0))

        # 计算趋势信号
        if upgrades > downgrades:
            trend_signal: Literal["bullish", "bearish", "neutral"] = "bullish"
        elif downgrades > upgrades:
            trend_signal = "bearish"
        else:
            trend_signal = "neutral"

        return {
            "upgrades": upgrades,
            "downgrades": downgrades,
            "maintains": maintains,
            "initiations": initiations,
            "trend_signal": trend_signal,
        }

    def get_rating_trend(self, ticker: str, days: int = 30) -> dict:
        """
        获取近期评级趋势统计

        用于判断：
        - upgrades > downgrades → 市场预期改善
        - downgrades > upgrades → 市场预期恶化

        Args:
            ticker: 股票代码，如 "601985.SH"
            days: 统计天数，默认 30 天

        Returns:
            dict: {
                "upgrades": 上调数量,
                "downgrades": 下调数量,
                "maintains": 维持数量,
                "initiations": 首次评级数量,
                "trend_signal": 趋势信号 ("bullish"/"bearish"/"neutral")
            }
        """
        # 检查市场支持
        if not self.supports_market(ticker):
            logger.warning(f"[{ticker}] 非 A 股，RatingChangeFetcher 不支持")
            return {
                "upgrades": 0,
                "downgrades": 0,
                "maintains": 0,
                "initiations": 0,
                "trend_signal": "neutral",
            }

        # 提取纯代码
        symbol = self.extract_symbol(ticker)

        try:
            import akshare as ak

            df = ak.stock_institute_recommend_detail(symbol=symbol)
        except Exception as e:
            error_msg = f"AkShare 机构评级趋势获取失败: {e}"
            logger.warning(f"[{ticker}] {error_msg}")
            return {
                "upgrades": 0,
                "downgrades": 0,
                "maintains": 0,
                "initiations": 0,
                "trend_signal": "neutral",
            }

        if df is None or df.empty:
            logger.debug(f"[{ticker}] 无机构评级趋势数据")
            return {
                "upgrades": 0,
                "downgrades": 0,
                "maintains": 0,
                "initiations": 0,
                "trend_signal": "neutral",
            }

        # 过滤时间范围
        cutoff_date = datetime.now().date() - timedelta(days=days)
        filtered_df = self._filter_by_date(df, cutoff_date)

        return self._calculate_rating_trend(filtered_df)

    def _filter_by_date(
        self, df: pd.DataFrame, cutoff_date: datetime.date
    ) -> pd.DataFrame:
        """
        按日期过滤 DataFrame

        Args:
            df: 原始 DataFrame
            cutoff_date: 截止日期

        Returns:
            pd.DataFrame: 过滤后的 DataFrame
        """
        filtered_indices = []

        for idx, row in df.iterrows():
            try:
                published_at = self._parse_date(row.get("日期", ""))
                if published_at is not None and published_at.date() >= cutoff_date:
                    filtered_indices.append(idx)
            except Exception:
                continue

        if not filtered_indices:
            return pd.DataFrame()

        return df.loc[filtered_indices]
