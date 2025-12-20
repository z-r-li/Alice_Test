"""
Tushare 行情数据提供者 - A股市场
"""
from __future__ import annotations

import os
from datetime import datetime

import tushare as ts

from .base import DataFetchError, QuotesProvider
from ..models import QuoteData


class TushareQuotesProvider(QuotesProvider):
    """Tushare A股行情数据提供者"""

    # 支持的市场后缀
    SUPPORTED_SUFFIXES = (".SH", ".SZ")

    def __init__(self, api_token: str | None = None):
        """
        初始化 Tushare 客户端

        Args:
            api_token: Tushare API Token，可从环境变量 TUSHARE_TOKEN 读取

        Raises:
            DataFetchError: Token 未配置时抛出
        """
        self._token = api_token or os.environ.get("TUSHARE_TOKEN")
        if not self._token:
            raise DataFetchError("Tushare API token not configured. "
                                 "Set TUSHARE_TOKEN environment variable or pass api_token parameter.")

        ts.set_token(self._token)
        self._pro = ts.pro_api()

    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        """
        获取 A 股标的行情数据

        Args:
            ticker: A股代码，如 "601985.SH"、"000001.SZ"
            date: 查询日期，默认为最新交易日

        Returns:
            QuoteData: 包含 price_close, pe_ttm, pb, turnover_rate 等

        Raises:
            DataFetchError: 数据获取失败时抛出
        """
        ticker = ticker.strip().upper()

        if not self.is_market_supported(ticker):
            raise DataFetchError(f"Unsupported market suffix. Expected {self.SUPPORTED_SUFFIXES}", ticker)

        try:
            # 格式化日期
            trade_date = date.strftime("%Y%m%d") if date else None

            # 获取日线行情数据（收盘价）
            if trade_date:
                daily_df = self._pro.daily(ts_code=ticker, trade_date=trade_date)
            else:
                # 获取最近的交易日数据
                daily_df = self._pro.daily(ts_code=ticker, limit=1)

            if daily_df is None or daily_df.empty:
                raise DataFetchError(f"No daily data available", ticker)

            # 获取交易日期
            actual_trade_date = daily_df.iloc[0]["trade_date"]

            # 获取每日基本指标（PE_TTM, PB, 换手率）
            basic_df = self._pro.daily_basic(ts_code=ticker, trade_date=actual_trade_date)

            if basic_df is None or basic_df.empty:
                raise DataFetchError(f"No basic data available for {actual_trade_date}", ticker)

            # 提取数据
            daily_row = daily_df.iloc[0]
            basic_row = basic_df.iloc[0]

            # 解析日期
            quote_date = datetime.strptime(str(actual_trade_date), "%Y%m%d")

            return QuoteData(
                date=quote_date,
                ticker=ticker,
                price_close=float(daily_row["close"]),
                pe_ttm=self._safe_float(basic_row.get("pe_ttm")),
                pb=self._safe_float(basic_row.get("pb")),
                turnover_rate=self._safe_float(basic_row.get("turnover_rate")),
                market_cap=self._safe_float(basic_row.get("total_mv")),
                volume=self._safe_float(daily_row.get("vol")),
            )

        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"Failed to fetch quote: {e}", ticker) from e

    def get_historical_quotes(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[QuoteData]:
        """
        获取 A 股历史行情

        Args:
            ticker: A股代码，如 "601985.SH"、"000001.SZ"
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            list[QuoteData]: 历史行情数据列表，按日期升序排列

        Raises:
            DataFetchError: 数据获取失败时抛出
        """
        ticker = ticker.strip().upper()

        if not self.is_market_supported(ticker):
            raise DataFetchError(f"Unsupported market suffix. Expected {self.SUPPORTED_SUFFIXES}", ticker)

        try:
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")

            # 获取日线行情数据
            daily_df = self._pro.daily(
                ts_code=ticker,
                start_date=start_str,
                end_date=end_str,
            )

            if daily_df is None or daily_df.empty:
                return []

            # 获取每日基本指标
            basic_df = self._pro.daily_basic(
                ts_code=ticker,
                start_date=start_str,
                end_date=end_str,
            )

            # 创建基本指标字典，以 trade_date 为键
            basic_dict = {}
            if basic_df is not None and not basic_df.empty:
                for _, row in basic_df.iterrows():
                    basic_dict[row["trade_date"]] = row

            # 构建结果列表
            quotes = []
            for _, daily_row in daily_df.iterrows():
                trade_date = daily_row["trade_date"]
                quote_date = datetime.strptime(str(trade_date), "%Y%m%d")
                basic_row = basic_dict.get(trade_date, {})

                quote = QuoteData(
                    date=quote_date,
                    ticker=ticker,
                    price_close=float(daily_row["close"]),
                    pe_ttm=self._safe_float(basic_row.get("pe_ttm") if basic_row else None),
                    pb=self._safe_float(basic_row.get("pb") if basic_row else None),
                    turnover_rate=self._safe_float(basic_row.get("turnover_rate") if basic_row else None),
                    market_cap=self._safe_float(basic_row.get("total_mv") if basic_row else None),
                    volume=self._safe_float(daily_row.get("vol")),
                )
                quotes.append(quote)

            # 按日期升序排列
            quotes.sort(key=lambda q: q.date)
            return quotes

        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"Failed to fetch historical quotes: {e}", ticker) from e

    def is_market_supported(self, ticker: str) -> bool:
        """
        判断是否为 A 股代码

        Args:
            ticker: 证券代码

        Returns:
            bool: 是否支持（.SH 或 .SZ 后缀）
        """
        return ticker.upper().endswith(self.SUPPORTED_SUFFIXES)

    @staticmethod
    def _safe_float(value) -> float | None:
        """
        安全转换为浮点数

        Args:
            value: 待转换的值

        Returns:
            float | None: 转换后的浮点数，无效值返回 None
        """
        if value is None:
            return None
        try:
            import math
            result = float(value)
            if math.isnan(result) or math.isinf(result):
                return None
            return result
        except (ValueError, TypeError):
            return None
