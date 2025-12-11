"""
数据摄入模块的数据模型定义
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class TextItem:
    """单条文本数据项"""
    source: str  # 券商名称 / 媒体站点
    type: Literal["research", "news"]  # 文本类型
    title: str  # 标题
    summary: str  # 经正则抽取的摘要/结论/风险提示
    published_at: datetime  # 发布时间
    url: str | None = None  # 原文链接（可选）


@dataclass
class QuoteData:
    """行情数据"""
    date: datetime  # 交易日期
    ticker: str  # 证券代码
    price_close: float  # 收盘价
    pe_ttm: float | None = None  # 市盈率 (TTM)
    pb: float | None = None  # 市净率
    turnover_rate: float | None = None  # 换手率
    market_cap: float | None = None  # 总市值（可选）
    volume: float | None = None  # 成交量（可选）


@dataclass
class TickerRawData:
    """单个标的的完整原始数据"""
    date: datetime  # 数据采集日期
    ticker: str  # 证券代码
    name: str  # 标的名称
    quote: QuoteData  # 行情数据
    texts: list[TextItem] = field(default_factory=list)  # 文本数据列表
    status: Literal["ok", "data_error", "partial"] = "ok"  # 数据状态
    error_message: str | None = None  # 错误信息（若有）
