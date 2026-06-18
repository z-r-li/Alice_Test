"""
A 股机构盈利预测获取器（#65 新增可达共识源）

数据源: 东方财富 — AkShare `stock_profit_forecast_em()`
用途: 把「机构对公司未来盈利的一致预期」作为 sentiment / implied_growth 的素材，
      直接抬升 A 股共识素材条数。走 datacenter.eastmoney（本网络可达）。

要点（实测纠偏）:
- `stock_profit_forecast_em(symbol=...)` 的 symbol 是【行业板块名】而非股票代码；传代码会让
  接口内部取空→报错。故改为取【全市场一致预期表】(symbol="")，按「代码/名称」过滤到本标的
  （整表含每股 1 行的一致预期：研报数、近六月评级分布、各年度预测每股收益等）。
- 全市场表整轮复用（实例级 TTL 缓存）：盈利预测变化慢，避免每标的重复拉全表。
- 一致预期代表「当前预期」，非时间窗内的新闻，故不做 48h 硬过滤。
- 列名宽松匹配；任何获取/解析失败都优雅降级为空列表（不影响其他源）；绝不编造数字。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime

import pandas as pd

from ...models import TextItem
from ..base import TextProvider
from ..models import TextSourceType

logger = logging.getLogger("alice_test")

# 含这些关键词的列视为「预测/估值/评级」信息列，拼进摘要
_FORECAST_COL_KEYWORDS = ("每股收益", "净利润", "预测", "增长", "营收", "目标价", "评级")
_CODE_COLS = ("代码", "股票代码", "证券代码")
_NAME_COLS = ("名称", "股票简称", "证券简称", "简称")


def _first(row, *names: str) -> str:
    """从 row（pandas Series / dict）按候选列名取第一个非空值。"""
    for n in names:
        try:
            val = row[n]
        except (KeyError, TypeError, IndexError):
            continue
        if val is not None and str(val).strip() not in ("", "nan", "None", "-"):
            return str(val).strip()
    return ""


def _parse_dt(value) -> datetime | None:
    """宽松解析日期/时间，失败返回 None。"""
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


class ProfitForecastFetcher(TextProvider):
    """东方财富机构盈利预测获取器（一致预期 → implied_growth 素材）。"""

    # 全市场一致预期表的实例级缓存 TTL（秒）；盈利预测变化慢，整轮复用
    MARKET_CACHE_TTL_S: float = 3600.0

    def __init__(self) -> None:
        self._cached_df: pd.DataFrame | None = None
        self._cached_at: float = 0.0

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        if not self.supports_market(ticker):
            logger.warning(f"[{ticker}] 非 A 股，ProfitForecastFetcher 不支持")
            return []

        symbol = self.extract_symbol(ticker)
        df = self._get_market_df()
        if df is None or getattr(df, "empty", True):
            logger.debug(f"[{ticker}] 无盈利预测数据")
            return []

        try:
            return self._to_items(df, symbol, name, max_items)
        except Exception as e:  # 解析异常也优雅降级，不影响其他源
            logger.warning(f"[{ticker}] 盈利预测解析失败: {e}")
            return []

    def _get_market_df(self) -> pd.DataFrame | None:
        """取（缓存的）全市场一致预期表；失败返回 None（不缓存失败）。"""
        now = time.time()
        if (
            self._cached_df is not None
            and (now - self._cached_at) < self.MARKET_CACHE_TTL_S
        ):
            return self._cached_df
        try:
            import akshare as ak

            # symbol 为行业板块名；留空取全市场（整表含「代码/名称」逐股一致预期）
            df = ak.stock_profit_forecast_em(symbol="")
        except Exception as e:
            logger.warning(f"盈利预测全市场表获取失败: {e}")
            return None
        if df is not None and not getattr(df, "empty", True):
            self._cached_df = df
            self._cached_at = now
        return df

    def _to_items(
        self, df: pd.DataFrame, symbol: str, name: str, max_items: int
    ) -> list[TextItem]:
        df = self._filter_to_target(df, symbol, name)
        if df is None or df.empty:
            return []

        forecast_cols = [
            c for c in df.columns
            if any(k in str(c) for k in _FORECAST_COL_KEYWORDS)
        ]

        rows: list[tuple[datetime, TextItem]] = []
        for _, row in df.iterrows():
            institution = _first(row, "机构", "机构名称", "评级机构", "研究机构")
            analyst = _first(row, "研究员", "分析师")
            rating = _first(row, "评级", "投资评级", "最新评级", "东财评级")
            report_count = _first(row, "研报数", "机构数")
            published = _parse_dt(
                _first(row, "报告日期", "日期", "发布日期", "评级日期") or None
            ) or datetime.now()

            bits = []
            if report_count:
                bits.append(f"研报数 {report_count}")
            for c in forecast_cols:
                v = _first(row, c)
                if v:
                    bits.append(f"{c} {v}")
            forecast_str = "；".join(bits)

            if not (institution or rating or forecast_str):
                continue

            parts: list[str] = []
            if institution:
                parts.append(f"机构 {institution}")
            if analyst:
                parts.append(f"分析师 {analyst}")
            if rating:
                # 不用「评级:」冒号写法，避免协调器把研报误判为评级变动源
                parts.append(f"预测评级 {rating}")
            if forecast_str:
                parts.append(forecast_str)
            summary = "｜".join(parts)
            who = institution or name or "机构"
            title = f"机构一致盈利预测 · {who}"

            rows.append(
                (
                    published,
                    TextItem(
                        source="东财盈利预测",
                        type="research",
                        title=title,
                        summary=summary,
                        published_at=published,
                        url=None,
                    ),
                )
            )

        rows.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in rows[:max_items]]

    @staticmethod
    def _filter_to_target(
        df: pd.DataFrame, symbol: str, name: str
    ) -> pd.DataFrame:
        """按「代码/名称」过滤到本标的；含代码/名称列但无命中则返回空（避免串标的）。

        无代码/名称列时（如 per-stock 直查返回），原样返回交由后续解析。
        """
        code_col = next((c for c in df.columns if str(c) in _CODE_COLS), None)
        name_col = next((c for c in df.columns if str(c) in _NAME_COLS), None)
        if not code_col and not name_col:
            return df
        mask: list[bool] = []
        for _, row in df.iterrows():
            ok = False
            if code_col and symbol and symbol in str(row[code_col]):
                ok = True
            if name_col and name and str(name) in str(row[name_col]):
                ok = True
            mask.append(ok)
        return df[pd.Series(mask, index=df.index)]

    def get_source_name(self) -> str:
        return "东财盈利预测"

    def supports_market(self, ticker: str) -> bool:
        return self.detect_market(ticker) == "a_share"

    def get_supported_source_types(self) -> list[TextSourceType]:
        return [TextSourceType.FORECAST]
