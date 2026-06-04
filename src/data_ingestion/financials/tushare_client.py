"""
Tushare 财报数据提供者 - A 股（需 TUSHARE_TOKEN）

接口：
- pro.income(ts_code="601985.SH")    利润表：total_revenue / oper_cost / n_income_attr_p
- pro.cashflow(ts_code="601985.SH")  现金流量表：n_cashflow_act
"""
from __future__ import annotations

import tushare as ts

from .base import FinancialsFetchError, FinancialsProvider, safe_float
from .models import FinancialPeriod, FinancialReport


class TushareFinancialsProvider(FinancialsProvider):
    """Tushare A 股财报提供者（需 token）"""

    SUPPORTED_SUFFIXES = (".SH", ".SZ")

    def __init__(self, api_token: str | None = None):
        self._token = api_token
        self._pro = None

    def _api(self):
        if self._pro is None:
            if not self._token:
                raise FinancialsFetchError("Tushare token not configured")
            ts.set_token(self._token)
            self._pro = ts.pro_api()
        return self._pro

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

        pro = self._api()
        try:
            income = pro.income(ts_code=ticker)
            cash = pro.cashflow(ts_code=ticker)
        except Exception as e:
            raise FinancialsFetchError(
                f"Failed to fetch financial statements: {e}", ticker
            ) from e

        if income is None or income.empty:
            raise FinancialsFetchError("No income statement data available", ticker)

        # 现金流：end_date → 经营活动现金流净额（同一 end_date 取首条）
        ocf_by_period: dict[str, float | None] = {}
        if cash is not None and not cash.empty:
            for _, row in cash.iterrows():
                end_date = str(row.get("end_date"))
                if end_date not in ocf_by_period:
                    ocf_by_period[end_date] = safe_float(row.get("n_cashflow_act"))

        periods_map: dict[str, FinancialPeriod] = {}
        for _, row in income.iterrows():
            end_date = str(row.get("end_date"))  # "20241231"
            if period_type == "annual" and not end_date.endswith("1231"):
                continue
            if end_date in periods_map:  # 取首条（最新 report_type）
                continue

            revenue = safe_float(row.get("total_revenue"))
            if revenue is None:
                revenue = safe_float(row.get("revenue"))

            net_income = safe_float(row.get("n_income_attr_p"))
            if net_income is None:
                net_income = safe_float(row.get("n_income"))

            period = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            periods_map[end_date] = FinancialPeriod(
                period=period,
                revenue=revenue,
                operating_cost=safe_float(row.get("oper_cost")),
                net_income=net_income,
                operating_cashflow=ocf_by_period.get(end_date),
            )

        periods = [periods_map[k] for k in sorted(periods_map.keys())][-max_periods:]

        return FinancialReport(
            ticker=ticker,
            market="a_share",
            periods=periods,
            currency="CNY",
            source="tushare",
            status="ok" if periods else "data_error",
            error_message=None if periods else "No periods parsed",
        )

    def is_market_supported(self, ticker: str) -> bool:
        return ticker.upper().endswith(self.SUPPORTED_SUFFIXES)
