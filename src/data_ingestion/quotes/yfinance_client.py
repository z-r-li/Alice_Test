"""
yfinance 行情数据提供者 - 港股/美股市场
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import yfinance as yf

from .base import DataFetchError, QuotesProvider
from ..models import QuoteData


class YFinanceQuotesProvider(QuotesProvider):
    """
    yfinance 港美股行情数据提供者

    支持港股（.HK 后缀）和美股（无后缀或非 A 股后缀）数据获取。
    yfinance 是免费 API，无需 API Token。

    Examples:
        >>> provider = YFinanceQuotesProvider()
        >>> # 获取腾讯港股数据
        >>> quote = provider.get_quote("0700.HK")
        >>> # 获取苹果美股数据
        >>> quote = provider.get_quote("AAPL")
    """

    # A股市场后缀，用于排除
    A_SHARE_SUFFIXES = (".SH", ".SZ")

    # 请求间隔（秒），避免触发频率限制
    REQUEST_INTERVAL = 0.5

    def __init__(self, request_interval: float = 0.5):
        """
        初始化 yfinance 客户端

        Args:
            request_interval: 请求间隔时间（秒），默认 0.5 秒
        """
        self._request_interval = request_interval
        self._last_request_time: float = 0

    def _rate_limit(self) -> None:
        """
        请求频率限制

        确保两次请求之间有足够的时间间隔，避免触发 API 限制。
        """
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_interval:
            time.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()

    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        """
        获取港/美股标的行情数据

        Args:
            ticker: 港股如 "0700.HK"，美股如 "AAPL"
            date: 查询日期，默认为最新交易日

        Returns:
            QuoteData: 行情数据，包含 price_close, pe_ttm, pb, turnover_rate 等

        Raises:
            DataFetchError: 数据获取失败时抛出
        """
        ticker = ticker.strip().upper()

        if not self.is_market_supported(ticker):
            raise DataFetchError(
                f"Unsupported market. Ticker {ticker} appears to be an A-share stock.",
                ticker
            )

        try:
            self._rate_limit()

            # 创建 Ticker 对象
            yf_ticker = yf.Ticker(ticker)

            # 获取历史数据
            if date:
                # 获取指定日期前后的数据范围
                start_date = date - timedelta(days=5)
                end_date = date + timedelta(days=1)
                history = yf_ticker.history(
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                )
                # 筛选指定日期或之前最近的交易日
                if history.empty:
                    raise DataFetchError(f"No historical data available for date {date}", ticker)

                # 查找目标日期或之前最近的数据
                target_date_str = date.strftime("%Y-%m-%d")
                history_filtered = history[history.index <= target_date_str]
                if history_filtered.empty:
                    raise DataFetchError(f"No data available for or before {date}", ticker)
                history = history_filtered.iloc[[-1]]  # 取最后一行
            else:
                # 获取最近的交易日数据
                history = yf_ticker.history(period="5d")
                if history.empty:
                    raise DataFetchError("No recent historical data available", ticker)
                history = history.iloc[[-1]]  # 取最后一行

            # 提取历史数据
            row = history.iloc[0]
            trade_date = history.index[0].to_pydatetime()

            # 获取估值指标（info 调用可能较慢）
            self._rate_limit()
            info = yf_ticker.info

            # 计算换手率：Volume / SharesOutstanding * 100
            turnover_rate = self._calculate_turnover_rate(
                volume=row.get("Volume"),
                shares_outstanding=info.get("sharesOutstanding"),
            )

            return QuoteData(
                date=trade_date,
                ticker=ticker,
                price_close=float(row["Close"]),
                pe_ttm=self._safe_float(info.get("trailingPE")),
                pb=self._safe_float(info.get("priceToBook")),
                turnover_rate=turnover_rate,
                market_cap=self._safe_float(info.get("marketCap")),
                volume=self._safe_float(row.get("Volume")),
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
        获取港/美股历史行情

        Args:
            ticker: 港股如 "0700.HK"，美股如 "AAPL"
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            list[QuoteData]: 历史行情数据列表，按日期升序排列

        Raises:
            DataFetchError: 数据获取失败时抛出

        Note:
            历史数据仅包含价格和成交量信息，不包含 PE/PB 等估值指标
            （yfinance 的 info 仅提供当前估值）
        """
        ticker = ticker.strip().upper()

        if not self.is_market_supported(ticker):
            raise DataFetchError(
                f"Unsupported market. Ticker {ticker} appears to be an A-share stock.",
                ticker
            )

        try:
            self._rate_limit()

            yf_ticker = yf.Ticker(ticker)

            # 获取历史数据
            history = yf_ticker.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            )

            if history.empty:
                return []

            # 获取流通股数用于计算换手率（仅当前值）
            self._rate_limit()
            info = yf_ticker.info
            shares_outstanding = info.get("sharesOutstanding")

            # 构建结果列表
            quotes = []
            for idx, row in history.iterrows():
                trade_date = idx.to_pydatetime()

                # 计算换手率
                turnover_rate = self._calculate_turnover_rate(
                    volume=row.get("Volume"),
                    shares_outstanding=shares_outstanding,
                )

                quote = QuoteData(
                    date=trade_date,
                    ticker=ticker,
                    price_close=float(row["Close"]),
                    pe_ttm=None,  # 历史 PE 不可用
                    pb=None,  # 历史 PB 不可用
                    turnover_rate=turnover_rate,
                    market_cap=None,  # 历史市值不可用
                    volume=self._safe_float(row.get("Volume")),
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
        判断是否为港股/美股代码

        Args:
            ticker: 证券代码

        Returns:
            bool: 是否支持
                - True: 港股（.HK 后缀）或美股（无后缀或非 A 股后缀）
                - False: A 股（.SH 或 .SZ 后缀）
        """
        ticker_upper = ticker.upper()
        # 排除 A 股
        if ticker_upper.endswith(self.A_SHARE_SUFFIXES):
            return False
        # 支持港股和其他市场
        return True

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

    def _calculate_turnover_rate(
        self,
        volume: float | None,
        shares_outstanding: float | None,
    ) -> float | None:
        """
        计算换手率

        Args:
            volume: 成交量（股）
            shares_outstanding: 流通股数

        Returns:
            float | None: 换手率（百分比），如无法计算则返回 None
        """
        volume = self._safe_float(volume)
        shares = self._safe_float(shares_outstanding)

        if volume is None or shares is None or shares <= 0:
            return None

        return (volume / shares) * 100
