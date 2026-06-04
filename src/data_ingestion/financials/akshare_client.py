"""
AkShare 财报数据提供者 - A 股（基于东方财富 *_by_report_em 接口，免 token）

接口（已对 601985.SH 实测可用）：
- ak.stock_profit_sheet_by_report_em(symbol="SH601985")  利润表
    关键列：REPORT_DATE / CURRENCY / TOTAL_OPERATE_INCOME(营业总收入) /
            OPERATE_COST(营业成本) / PARENT_NETPROFIT(归母净利润) / NETPROFIT(净利润)
- ak.stock_cash_flow_sheet_by_report_em(symbol="SH601985")  现金流量表
    关键列：REPORT_DATE / NETCASH_OPERATE(经营活动产生的现金流量净额)
"""
from __future__ import annotations

import akshare as ak

from .base import FinancialsFetchError, FinancialsProvider, safe_float
from .models import FinancialPeriod, FinancialReport


class AkShareFinancialsProvider(FinancialsProvider):
    """AkShare A 股财报提供者（东方财富数据源，免 API Token）"""

    SUPPORTED_SUFFIXES = (".SH", ".SZ")

    def get_financials(
        self,
        ticker: str,
        max_periods: int = 5,
        period_type: str = "annual",
    ) -> FinancialReport:
        ticker = ticker.strip().upper()
        if not self.is_market_supported(ticker):
            raise FinancialsFetchError(
                f"Unsupported market suffix. Expected {self.SUPPORTED_SUFFIXES}", ticker
            )

        em_symbol = self._to_em_symbol(ticker)  # 601985.SH → SH601985
        try:
            profit_df = ak.stock_profit_sheet_by_report_em(symbol=em_symbol)
            cash_df = ak.stock_cash_flow_sheet_by_report_em(symbol=em_symbol)
        except Exception as e:
            raise FinancialsFetchError(
                f"Failed to fetch financial statements: {e}", ticker
            ) from e

        if profit_df is None or profit_df.empty:
            raise FinancialsFetchError("No income statement data available", ticker)

        # 现金流：报告期 → 经营活动现金流净额
        ocf_by_period: dict[str, float | None] = {}
        if cash_df is not None and not cash_df.empty:
            for _, row in cash_df.iterrows():
                period = str(row.get("REPORT_DATE"))[:10]
                ocf_by_period[period] = safe_float(row.get("NETCASH_OPERATE"))

        currency: str | None = None
        periods_map: dict[str, FinancialPeriod] = {}
        for _, row in profit_df.iterrows():
            period = str(row.get("REPORT_DATE"))[:10]
            if period_type == "annual" and not period.endswith("-12-31"):
                continue

            if currency is None:
                cur = row.get("CURRENCY")
                currency = str(cur) if cur else None

            revenue = safe_float(row.get("TOTAL_OPERATE_INCOME"))
            if revenue is None:
                revenue = safe_float(row.get("OPERATE_INCOME"))

            net_income = safe_float(row.get("PARENT_NETPROFIT"))
            if net_income is None:
                net_income = safe_float(row.get("NETPROFIT"))

            periods_map[period] = FinancialPeriod(
                period=period,
                revenue=revenue,
                operating_cost=safe_float(row.get("OPERATE_COST")),
                net_income=net_income,
                operating_cashflow=ocf_by_period.get(period),
            )

        periods = [periods_map[p] for p in sorted(periods_map.keys())][-max_periods:]

        return FinancialReport(
            ticker=ticker,
            market="a_share",
            periods=periods,
            currency=currency,
            source="akshare_em",
            status="ok" if periods else "data_error",
            error_message=None if periods else "No periods parsed",
        )

    def is_market_supported(self, ticker: str) -> bool:
        return ticker.upper().endswith(self.SUPPORTED_SUFFIXES)

    @staticmethod
    def _to_em_symbol(ticker: str) -> str:
        """601985.SH → SH601985；000001.SZ → SZ000001"""
        code, _, suffix = ticker.partition(".")
        return f"{suffix}{code}"
