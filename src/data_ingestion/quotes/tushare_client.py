"""
Tushare 行情数据提供者 - A股市场
"""
from datetime import datetime

from .base import QuotesProvider
from ..models import QuoteData


class TushareQuotesProvider(QuotesProvider):
    """Tushare A股行情数据提供者"""

    def __init__(self, api_token: str | None = None):
        """
        初始化 Tushare 客户端

        Args:
            api_token: Tushare API Token，可从环境变量 TUSHARE_TOKEN 读取
        """
        self._token = api_token
        # TODO: 初始化 tushare pro api

    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData:
        """
        获取 A 股标的行情数据

        Args:
            ticker: A股代码，如 "601985.SH"、"000001.SZ"
            date: 查询日期

        Returns:
            QuoteData: 包含 price_close, pe_ttm, pb, turnover_rate 等
        """
        # TODO: 调用 tushare daily + daily_basic 接口
        raise NotImplementedError

    def get_historical_quotes(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[QuoteData]:
        """获取 A 股历史行情"""
        # TODO: 实现历史数据获取
        raise NotImplementedError

    def is_market_supported(self, ticker: str) -> bool:
        """判断是否为 A 股代码"""
        return ticker.endswith((".SH", ".SZ"))
