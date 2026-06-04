"""
yfinance 财报数据提供者 - 港股 / 美股

使用 yfinance 的年度报表与 info：
- Ticker.financials   利润表（行含 "Total Revenue" / "Cost Of Revenue" / "Gross Profit" / "Net Income"）
- Ticker.cashflow     现金流量表（行含 "Operating Cash Flow"）
- Ticker.info         forwardPE / pegRatio / trailingPegRatio（前瞻估值，A 股通常没有）
"""
from __future__ import annotations

import yfinance as yf

from .base import FinancialsFetchError, FinancialsProvider, detect_market, safe_float
from .models import FinancialPeriod, FinancialReport


class YFinanceFinancialsProvider(FinancialsProvider):
    """yfinance 港美股财报提供者（免 token）"""

    A_SHARE_SUFFIXES = (".SH", ".SZ")

    def get_financials(
        self,
        ticker: str,
        max_periods: int = 5,
        period_type: str = "annual",
    ) -> FinancialReport:
        ticker = ticker.strip().upper()
        if not self.is_market_supported(ticker):
            raise FinancialsFetchError(
                f"Unsupported market. {ticker} appears to be an A-share stock.", ticker
            )

        try:
            yf_ticker = yf.Ticker(ticker)
            income = (
                yf_ticker.quarterly_financials
                if period_type == "quarterly"
                else yf_ticker.financials
            )
            cashflow = (
                yf_ticker.quarterly_cashflow
                if period_type == "quarterly"
                else yf_ticker.cashflow
            )
            info = yf_ticker.info or {}
        except Exception as e:
            raise FinancialsFetchError(f"Failed to fetch financials: {e}", ticker) from e

        if income is None or income.empty:
            raise FinancialsFetchError("No income statement data available", ticker)

        rev_row = self._row(income, "Total Revenue", "TotalRevenue")
        cost_row = self._row(income, "Cost Of Revenue", "CostOfRevenue")
        gross_row = self._row(income, "Gross Profit", "GrossProfit")
        ni_row = self._row(
            income, "Net Income", "NetIncome", "Net Income Common Stockholders"
        )
        ocf_row = self._row(
            cashflow,
            "Operating Cash Flow",
            "Total Cash From Operating Activities",
            "OperatingCashFlow",
        )

        periods_map: dict[str, FinancialPeriod] = {}
        for col in income.columns:
            period = str(col)[:10]
            revenue = safe_float(rev_row.get(col))
            operating_cost = safe_float(cost_row.get(col))
            # 缺营业成本时用 营收 − 毛利 反推
            if operating_cost is None:
                gross = safe_float(gross_row.get(col))
                if revenue is not None and gross is not None:
                    operating_cost = revenue - gross
            periods_map[period] = FinancialPeriod(
                period=period,
                revenue=revenue,
                operating_cost=operating_cost,
                net_income=safe_float(ni_row.get(col)),
                operating_cashflow=safe_float(ocf_row.get(col)),
            )

        periods = [periods_map[p] for p in sorted(periods_map.keys())][-max_periods:]

        return FinancialReport(
            ticker=ticker,
            market=detect_market(ticker),
            periods=periods,
            currency=(info.get("financialCurrency") or info.get("currency")),
            forward_pe=safe_float(info.get("forwardPE")),
            peg_ratio=safe_float(info.get("pegRatio") or info.get("trailingPegRatio")),
            source="yfinance",
            status="ok" if periods else "data_error",
            error_message=None if periods else "No periods parsed",
        )

    def is_market_supported(self, ticker: str) -> bool:
        return not ticker.upper().endswith(self.A_SHARE_SUFFIXES)

    @staticmethod
    def _row(df, *names: str) -> dict:
        """从报表 DataFrame 中按候选行名取一行（列→值 dict），找不到返回空 dict"""
        if df is None or df.empty:
            return {}
        for name in names:
            if name in df.index:
                return df.loc[name].to_dict()
        return {}
