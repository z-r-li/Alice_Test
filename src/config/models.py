"""
配置数据模型定义
"""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LLMConfig:
    """LLM API 配置"""
    provider: Literal["deepseek"] = "deepseek"
    api_key: str = ""  # 支持从环境变量注入
    model: str = "deepseek-chat"
    temperature: float = 0.0  # 必须为 0，保证评分稳定
    max_tokens: int = 4096


@dataclass
class QuotesSourceConfig:
    """行情数据源配置"""
    a_share: Literal["tushare", "akshare"] = "tushare"
    hk_us: Literal["yfinance"] = "yfinance"


@dataclass
class TextSourceConfig:
    """文本数据源配置"""
    research_providers: list[str] = field(default_factory=list)
    news_sites: list[str] = field(default_factory=list)
    search_entrypoints: list[str] = field(default_factory=list)


@dataclass
class DataSourcesConfig:
    """数据源总配置"""
    quotes: QuotesSourceConfig = field(default_factory=QuotesSourceConfig)
    text: TextSourceConfig = field(default_factory=TextSourceConfig)


@dataclass
class TargetConfig:
    """单个标的配置"""
    ticker: str  # 证券代码，如 "601985.SH"
    name: str  # 标的名称，如 "中国核电"
    thesis: str  # 用户宏观信念描述


@dataclass
class SchedulerConfig:
    """调度配置"""
    cron: str = "0 18 * * MON-FRI"  # 默认每交易日 18:00


@dataclass
class GapThresholdConfig:
    """Gap 判定阈值配置"""
    opportunity_gap_min: float = 10.0  # Gap > 10 视为机会
    opportunity_sentiment_max: int = 40  # 情绪 < 40 视为悲观
    overheated_sentiment_min: int = 80  # 情绪 > 80 视为过热


@dataclass
class AppConfig:
    """应用总配置"""
    llm_api: LLMConfig = field(default_factory=LLMConfig)
    data_sources: DataSourcesConfig = field(default_factory=DataSourcesConfig)
    targets: list[TargetConfig] = field(default_factory=list)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    gap_thresholds: GapThresholdConfig = field(default_factory=GapThresholdConfig)
