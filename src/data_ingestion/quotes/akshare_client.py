"""
AkShare 行情数据提供者 - A股市场备选
"""
from __future__ import annotations

import math
from datetime import datetime

import akshare as ak

from .base import DataFetchError, QuotesProvider
from ..models import QuoteData


class AkShareQuotesProvider(QuotesProvider):
    """AkShare A股行情数据提供者（免费备选）"""

    # 支持的市场后缀
    SUPPORTED_SUFFIXES = (".SH", ".SZ")

    def __init__(self):
        """初始化 AkShare 客户端（无需 API Token）"""
        pass

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
            raise DataFetchError(
                f"Unsupported market suffix. Expected {self.SUPPORTED_SUFFIXES}", ticker
            )

        try:
            # 转换 ticker 格式: 601985.SH → 601985
            symbol = self._convert_ticker(ticker)

            # 确定查询日期范围
            if date:
                start_date = date.strftime("%Y%m%d")
                end_date = date.strftime("%Y%m%d")
            else:
                # 获取最近的交易日数据（获取最近30天）
                end_dt = datetime.now()
                start_dt = datetime(end_dt.year, end_dt.month, 1)
                start_date = start_dt.strftime("%Y%m%d")
                end_date = end_dt.strftime("%Y%m%d")

            # 获取历史行情数据
            hist_df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",  # 前复权
            )

            if hist_df is None or hist_df.empty:
                raise DataFetchError("No historical data available", ticker)

            # 获取最新（或指定日期）的行情
            hist_row = hist_df.iloc[-1]
            trade_date_str = str(hist_row["日期"])
            quote_date = datetime.strptime(trade_date_str, "%Y-%m-%d")

            # 获取估值信息（PE/PB等）
            pe_ttm = None
            pb = None
            market_cap = None
            turnover_rate = None

            try:
                info_df = ak.stock_individual_info_em(symbol=symbol)
                if info_df is not None and not info_df.empty:
                    # info_df 结构: item, value
                    info_dict = dict(zip(info_df["item"], info_df["value"]))
                    pe_ttm = self._safe_float(info_dict.get("市盈率(动态)"))
                    pb = self._safe_float(info_dict.get("市净率"))
                    # 总市值可能是字符串如 "1234.56亿"
                    market_cap_str = info_dict.get("总市值")
                    market_cap = self._parse_market_cap(market_cap_str)
            except Exception:
                # 估值信息获取失败不影响主流程
                pass

            # 从历史数据中获取换手率和成交量
            turnover_rate = self._safe_float(hist_row.get("换手率"))
            volume = self._safe_float(hist_row.get("成交量"))

            return QuoteData(
                date=quote_date,
                ticker=ticker,
                price_close=float(hist_row["收盘"]),
                pe_ttm=pe_ttm,
                pb=pb,
                turnover_rate=turnover_rate,
                market_cap=market_cap,
                volume=volume,
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
            raise DataFetchError(
                f"Unsupported market suffix. Expected {self.SUPPORTED_SUFFIXES}", ticker
            )

        try:
            symbol = self._convert_ticker(ticker)
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")

            # 获取历史行情数据
            hist_df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq",
            )

            if hist_df is None or hist_df.empty:
                return []

            # 尝试获取估值信息（仅获取最新的一次，用于参考）
            pe_ttm = None
            pb = None
            market_cap = None

            try:
                info_df = ak.stock_individual_info_em(symbol=symbol)
                if info_df is not None and not info_df.empty:
                    info_dict = dict(zip(info_df["item"], info_df["value"]))
                    pe_ttm = self._safe_float(info_dict.get("市盈率(动态)"))
                    pb = self._safe_float(info_dict.get("市净率"))
                    market_cap_str = info_dict.get("总市值")
                    market_cap = self._parse_market_cap(market_cap_str)
            except Exception:
                pass

            # 构建结果列表
            quotes = []
            for _, row in hist_df.iterrows():
                trade_date_str = str(row["日期"])
                quote_date = datetime.strptime(trade_date_str, "%Y-%m-%d")

                quote = QuoteData(
                    date=quote_date,
                    ticker=ticker,
                    price_close=float(row["收盘"]),
                    pe_ttm=pe_ttm,  # 历史PE需要单独获取，这里使用最新值作为参考
                    pb=pb,
                    turnover_rate=self._safe_float(row.get("换手率")),
                    market_cap=market_cap,
                    volume=self._safe_float(row.get("成交量")),
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
    def _convert_ticker(ticker: str) -> str:
        """
        转换 ticker 格式为 akshare 格式

        Args:
            ticker: 标准格式，如 "601985.SH"

        Returns:
            str: akshare 格式，如 "601985"
        """
        # 去掉 .SH 或 .SZ 后缀
        if "." in ticker:
            return ticker.split(".")[0]
        return ticker

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
            result = float(value)
            if math.isnan(result) or math.isinf(result):
                return None
            return result
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_market_cap(value: str | None) -> float | None:
        """
        解析市值字符串

        Args:
            value: 市值字符串，如 "1234.56亿" 或 "56.78万"

        Returns:
            float | None: 市值（元），无效值返回 None
        """
        if value is None:
            return None
        try:
            value_str = str(value).strip()
            if not value_str:
                return None

            # 处理单位
            if "亿" in value_str:
                num = float(value_str.replace("亿", ""))
                return num * 1e8
            elif "万" in value_str:
                num = float(value_str.replace("万", ""))
                return num * 1e4
            else:
                return float(value_str)
        except (ValueError, TypeError):
            return None
