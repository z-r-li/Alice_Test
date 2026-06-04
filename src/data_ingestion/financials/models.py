"""
财报数据模型 (S4 输入)

`FinancialReport` 承载逐期 (periodized) 的原始财务报表数据，由 FinancialsProvider 摄入；
`FinancialAnalysisEngine`（engines/financial_analysis.py）据此计算 forward PE / PEG /
收入·毛利·现金流趋势并产出 Evidence。

约定：
- periods 按报告期升序排列（旧 → 新），便于计算趋势 / CAGR。
- 金额为报表原始单位（A 股为人民币元，港美股为报表币种）；缺失值一律 None，绝不臆造。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Market = Literal["a_share", "hk", "us"]


@dataclass
class FinancialPeriod:
    """单个报告期的关键财务科目"""

    period: str  # 报告期，如 "2024-12-31"
    revenue: float | None = None  # 营业总收入
    operating_cost: float | None = None  # 营业成本（用于毛利率）
    net_income: float | None = None  # 归母净利润
    operating_cashflow: float | None = None  # 经营活动产生的现金流量净额

    @property
    def gross_margin(self) -> float | None:
        """毛利率 (%) = (营业收入 − 营业成本) / 营业收入"""
        if self.revenue and self.operating_cost is not None:
            return (self.revenue - self.operating_cost) / self.revenue * 100
        return None

    @property
    def net_margin(self) -> float | None:
        """净利率 (%) = 归母净利润 / 营业收入"""
        if self.revenue and self.net_income is not None:
            return self.net_income / self.revenue * 100
        return None


@dataclass
class FinancialReport:
    """一个标的的多期财务报表（升序）"""

    ticker: str
    market: Market
    periods: list[FinancialPeriod] = field(default_factory=list)  # 升序（旧→新）
    currency: str | None = None
    # provider 直接提供的前瞻指标（yfinance 有；A 股通常为 None，由引擎按需推导或标注需尽调）
    forward_pe: float | None = None
    peg_ratio: float | None = None
    source: str = ""
    status: Literal["ok", "partial", "data_error"] = "ok"
    error_message: str | None = None

    @property
    def latest(self) -> FinancialPeriod | None:
        """最新一期"""
        return self.periods[-1] if self.periods else None

    def is_empty(self) -> bool:
        return not self.periods
