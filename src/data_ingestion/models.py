"""
数据摄入模块的数据模型定义

使用 Pydantic v2 定义行情数据和文本数据的结构化模型。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TextItem(BaseModel):
    """
    单条文本数据项

    表示从研报或新闻中抓取的一条文本信息。

    Attributes:
        source: 数据来源，如券商名称或媒体站点
        type: 文本类型，"research" 表示研报，"news" 表示新闻
        title: 文本标题
        summary: 经正则抽取的摘要/结论/风险提示
        published_at: 发布时间
        url: 原文链接（可选）

    Example:
        >>> item = TextItem(
        ...     source="中信证券",
        ...     type="research",
        ...     title="中国核电深度报告",
        ...     summary="AI 算力驱动电力需求增长...",
        ...     published_at=datetime.now()
        ... )
    """

    source: str = Field(..., min_length=1, description="数据来源")
    type: Literal["research", "news"] = Field(..., description="文本类型")
    title: str = Field(..., min_length=1, description="标题")
    summary: str = Field(..., description="摘要内容")
    published_at: datetime = Field(..., description="发布时间")
    url: str | None = Field(default=None, description="原文链接")

    def get_age_hours(self, now: datetime | None = None) -> float:
        """
        计算文本发布距今的小时数

        Args:
            now: 当前时间，默认为 datetime.now()

        Returns:
            float: 距今小时数
        """
        now = now or datetime.now()
        delta = now - self.published_at
        return delta.total_seconds() / 3600


class QuoteData(BaseModel):
    """
    行情数据

    表示某个标的在某一天的行情快照。

    Attributes:
        date: 交易日期
        ticker: 证券代码
        price_close: 收盘价
        pe_ttm: 市盈率 (TTM)
        pb: 市净率
        turnover_rate: 换手率（百分比）
        market_cap: 总市值（元）
        volume: 成交量（股）

    Example:
        >>> quote = QuoteData(
        ...     date=datetime.now(),
        ...     ticker="601985.SH",
        ...     price_close=8.88,
        ...     pe_ttm=15.5,
        ...     pb=1.2
        ... )
    """

    date: datetime = Field(..., description="交易日期")
    ticker: str = Field(..., min_length=1, description="证券代码")
    # ge=0：0.0 仅作行情缺失时的占位（main 降级路径，status=data_error），正常行情恒 > 0
    price_close: float = Field(..., ge=0, description="收盘价（0.0=占位，见 status）")
    pe_ttm: float | None = Field(default=None, description="市盈率 (TTM)")
    pb: float | None = Field(default=None, description="市净率")
    turnover_rate: float | None = Field(default=None, ge=0, description="换手率")
    market_cap: float | None = Field(default=None, ge=0, description="总市值")
    volume: float | None = Field(default=None, ge=0, description="成交量")

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        """规范化 ticker 格式"""
        return v.strip().upper()

    def get_valuation_summary(self) -> str:
        """
        获取估值摘要字符串

        Returns:
            str: 格式化的估值信息
        """
        parts = [f"Price: {self.price_close:.2f}"]
        if self.pe_ttm is not None:
            parts.append(f"PE(TTM): {self.pe_ttm:.1f}")
        if self.pb is not None:
            parts.append(f"PB: {self.pb:.2f}")
        return " | ".join(parts)


class TickerRawData(BaseModel):
    """
    单个标的的完整原始数据

    包含行情数据和相关文本数据，是 ConsensusEngine 的输入。

    Attributes:
        date: 数据采集日期
        ticker: 证券代码
        name: 标的名称
        quote: 行情数据
        texts: 文本数据列表（研报+新闻）
        status: 数据状态
        error_message: 错误信息（若有）

    Example:
        >>> raw_data = TickerRawData(
        ...     date=datetime.now(),
        ...     ticker="601985.SH",
        ...     name="中国核电",
        ...     quote=quote,
        ...     texts=[text_item1, text_item2]
        ... )
    """

    date: datetime = Field(..., description="数据采集日期")
    ticker: str = Field(..., min_length=1, description="证券代码")
    name: str = Field(..., min_length=1, description="标的名称")
    quote: QuoteData = Field(..., description="行情数据")
    texts: list[TextItem] = Field(default_factory=list, description="文本数据列表")
    status: Literal["ok", "data_error", "partial"] = Field(
        default="ok", description="数据状态"
    )
    error_message: str | None = Field(default=None, description="错误信息")

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        """规范化 ticker 格式"""
        return v.strip().upper()

    def get_text_count(self) -> dict[str, int]:
        """
        获取各类型文本数量

        Returns:
            dict: {"research": n, "news": m}
        """
        counts = {"research": 0, "news": 0}
        for text in self.texts:
            counts[text.type] += 1
        return counts

    def has_sufficient_data(self, min_texts: int = 1) -> bool:
        """
        检查是否有足够的数据进行分析

        Args:
            min_texts: 最少需要的文本数量

        Returns:
            bool: 是否有足够数据
        """
        return self.status == "ok" and len(self.texts) >= min_texts

    def to_llm_context(self) -> str:
        """
        转换为 LLM 输入格式的上下文字符串

        Returns:
            str: 格式化的上下文
        """
        lines = [
            f"标的: {self.name} ({self.ticker})",
            f"日期: {self.date.strftime('%Y-%m-%d')}",
            "",
            "估值信息:",
            f"  收盘价: {self.quote.price_close:.2f}",
        ]

        if self.quote.pe_ttm is not None:
            lines.append(f"  PE (TTM): {self.quote.pe_ttm:.1f}")
        if self.quote.pb is not None:
            lines.append(f"  PB: {self.quote.pb:.2f}")
        if self.quote.turnover_rate is not None:
            lines.append(f"  换手率: {self.quote.turnover_rate:.2f}%")

        if self.texts:
            lines.append("")
            lines.append(f"相关资讯 ({len(self.texts)} 条):")
            for i, text in enumerate(self.texts, 1):
                lines.append(f"  {i}. [{text.source}] ({text.type}) {text.title}")
                if text.summary:
                    lines.append(f"     摘要: {text.summary[:200]}...")

        return "\n".join(lines)
