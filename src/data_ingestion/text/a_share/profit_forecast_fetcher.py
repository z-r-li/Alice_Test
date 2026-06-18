"""
A 股机构盈利预测获取器（#65 新增可达共识源）

数据源: 东方财富 — AkShare `stock_profit_forecast_em(symbol=...)`
用途: 把「机构对公司未来盈利/增速的一致预期」作为 sentiment / implied_growth 的素材，
      直接抬升 A 股共识素材条数。走 datacenter.eastmoney（本网络可达）。

要点:
- 盈利预测代表「当前一致预期」，并非时间窗内的新闻，故按报告日期取最新 max_items 条，
  不做 48h 硬过滤（其余新闻/公告类源仍按窗口过滤）。
- 列名宽松匹配（机构/研究员/评级/各年度每股收益·净利润等），不同 akshare 版本兼容。
- 若返回的是含「代码/简称」列的宽表（疑似市场级），过滤到本标的，避免串标的。
- 任何获取/解析失败都优雅降级为空列表（不影响其他源）；绝不编造数字。
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd

from ...models import TextItem
from ..base import TextProvider
from ..models import TextSourceType

logger = logging.getLogger("alice_test")

# 含这些关键词的列视为「预测/估值」数值列，拼进摘要
_FORECAST_COL_KEYWORDS = ("每股收益", "净利润", "预测", "增长", "营收", "目标价", "评级")
_CODE_COLS = ("股票代码", "代码", "证券代码")
_NAME_COLS = ("股票简称", "名称", "证券简称", "简称")


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
        em_symbol = self._em_symbol(ticker)
        try:
            import akshare as ak

            df = ak.stock_profit_forecast_em(symbol=em_symbol)
        except Exception as e:
            logger.warning(f"[{ticker}] 盈利预测获取失败: {e}")
            return []

        if df is None or getattr(df, "empty", True):
            logger.debug(f"[{ticker}] 无盈利预测数据")
            return []

        try:
            return self._to_items(df, symbol, name, max_items)
        except Exception as e:  # 解析异常也优雅降级，不影响其他源
            logger.warning(f"[{ticker}] 盈利预测解析失败: {e}")
            return []

    @staticmethod
    def _em_symbol(ticker: str) -> str:
        """东财盈利预测接口的 symbol 形如 SH601985 / SZ000001；非沪深用纯代码兜底。"""
        t = ticker.upper()
        code = t.split(".")[0]
        if t.endswith(".SH"):
            return f"SH{code}"
        if t.endswith(".SZ"):
            return f"SZ{code}"
        return code

    def _to_items(
        self, df: pd.DataFrame, symbol: str, name: str, max_items: int
    ) -> list[TextItem]:
        # 若是含代码/简称的宽表（疑似市场级返回），先过滤到本标的，避免串标的
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
            published = _parse_dt(
                _first(row, "报告日期", "日期", "发布日期", "评级日期") or None
            ) or datetime.now()

            bits = []
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
            title = f"盈利预测 · {institution}" if institution else "机构盈利预测一致预期"

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
        """含代码/简称列时过滤到本标的；命中为空则退回原表（按 per-stock 查询处理）。"""
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
        if any(mask):
            return df[pd.Series(mask, index=df.index)]
        return df

    def get_source_name(self) -> str:
        return "东财盈利预测"

    def supports_market(self, ticker: str) -> bool:
        return self.detect_market(ticker) == "a_share"

    def get_supported_source_types(self) -> list[TextSourceType]:
        return [TextSourceType.FORECAST]
