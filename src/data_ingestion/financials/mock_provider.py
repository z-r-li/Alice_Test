"""
Mock 财报数据提供者 - 离线开发 / 测试用

为常见标的返回固定的、逐年增长的财务序列，支持所有市场，不触达任何网络。
用于 use_mock 离线流水线与单元测试（与 text/mock_provider.py 同思路）。
"""
from __future__ import annotations

from .base import FinancialsProvider, detect_market
from .models import FinancialPeriod, FinancialReport

# ticker -> (currency, forward_pe, peg, periods[(period, revenue, operating_cost, net_income, ocf)])
# 金额单位：报表原始货币单位（元 / 报表币种）；periods 升序。
_MOCK: dict[str, dict] = {
    "601985.SH": {
        "currency": "CNY",
        "forward_pe": None,  # A 股前瞻估值通常无公开数据
        "peg": None,
        "periods": [
            ("2021-12-31", 6.23e10, 3.55e10, 8.00e9, 2.45e10),
            ("2022-12-31", 6.83e10, 3.90e10, 8.84e9, 2.71e10),
            ("2023-12-31", 7.50e10, 4.31e10, 1.004e10, 3.02e10),
            ("2024-12-31", 7.72e10, 4.48e10, 1.051e10, 3.20e10),
            ("2025-12-31", 8.21e10, 4.82e10, 9.30e9, 3.74e10),
        ],
    },
    "600150.SH": {
        "currency": "CNY",
        "forward_pe": None,
        "peg": None,
        "periods": [
            ("2021-12-31", 5.95e11, 5.40e11, 2.0e9, 1.5e10),
            ("2022-12-31", 5.94e11, 5.45e11, 1.7e9, 1.2e10),
            ("2023-12-31", 7.48e11, 6.70e11, 2.96e9, 3.0e10),
            ("2024-12-31", 7.86e11, 6.90e11, 3.61e9, 3.6e10),
        ],
    },
    "0700.HK": {
        "currency": "CNY",
        "forward_pe": 14.0,
        "peg": 1.1,
        "periods": [
            ("2021-12-31", 5.60e11, 2.70e11, 2.24e11, 1.90e11),
            ("2022-12-31", 5.55e11, 2.90e11, 1.88e11, 1.70e11),
            ("2023-12-31", 6.09e11, 3.00e11, 1.15e11, 2.20e11),
            ("2024-12-31", 6.60e11, 3.10e11, 1.94e11, 2.60e11),
        ],
    },
    "AAPL": {
        "currency": "USD",
        "forward_pe": 28.0,
        "peg": 2.5,
        "periods": [
            ("2021-09-30", 3.65e11, 2.13e11, 9.46e10, 1.04e11),
            ("2022-09-30", 3.94e11, 2.23e11, 9.98e10, 1.22e11),
            ("2023-09-30", 3.83e11, 2.14e11, 9.70e10, 1.10e11),
            ("2024-09-30", 3.91e11, 2.10e11, 9.36e10, 1.18e11),
        ],
    },
    "_default_": {
        "currency": None,
        "forward_pe": None,
        "peg": None,
        "periods": [
            ("2022-12-31", 1.00e9, 6.00e8, 1.00e8, 1.50e8),
            ("2023-12-31", 1.20e9, 7.00e8, 1.30e8, 1.80e8),
            ("2024-12-31", 1.45e9, 8.20e8, 1.60e8, 2.10e8),
        ],
    },
}


class MockFinancialsProvider(FinancialsProvider):
    """固定假数据的财报提供者（离线 / 测试）"""

    def get_financials(
        self,
        ticker: str,
        max_periods: int = 5,
        period_type: str = "annual",
    ) -> FinancialReport:
        ticker_upper = ticker.strip().upper()
        spec = _MOCK.get(ticker_upper, _MOCK["_default_"])

        periods = [
            FinancialPeriod(
                period=p,
                revenue=rev,
                operating_cost=cost,
                net_income=ni,
                operating_cashflow=ocf,
            )
            for (p, rev, cost, ni, ocf) in spec["periods"]
        ][-max_periods:]

        return FinancialReport(
            ticker=ticker_upper,
            market=detect_market(ticker_upper),
            periods=periods,
            currency=spec["currency"],
            forward_pe=spec["forward_pe"],
            peg_ratio=spec["peg"],
            source="mock",
            status="ok",
        )

    def is_market_supported(self, ticker: str) -> bool:
        """Mock 支持所有市场"""
        return True

    @classmethod
    def get_available_tickers(cls) -> list[str]:
        return list(_MOCK.keys())
