"""
配置数据模型定义

使用 Pydantic v2 定义所有配置相关的数据模型，
支持从 config.yaml 加载并进行类型验证。
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class LLMConfig(BaseModel):
    """
    LLM API 配置

    Attributes:
        provider: LLM 提供商，当前仅支持 deepseek
        api_key: API 密钥，留空则从环境变量 DEEPSEEK_API_KEY 读取
        model: 模型名称
        temperature: 温度参数，必须为 0 以保证评分稳定
        max_tokens: 最大 token 数
        max_retries: 请求失败时的最大重试次数
    """

    provider: Literal["deepseek"] = "deepseek"
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10, description="最大重试次数")

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """PRD 要求 temperature 必须为 0 以保证评分稳定"""
        if v != 0.0:
            import warnings

            warnings.warn(
                f"temperature={v} 不为 0，可能导致情绪评分不稳定。"
                "PRD 要求 temperature=0 以保证可重复性。"
            )
        return v

    def get_api_key(self) -> str:
        """
        获取 API Key，优先从环境变量读取

        Returns:
            str: API Key

        Raises:
            ValueError: 未配置 API Key
        """
        key = os.environ.get("DEEPSEEK_API_KEY", self.api_key)
        if not key:
            raise ValueError(
                "未配置 DeepSeek API Key。"
                "请在 config.yaml 中设置 api_key 或设置环境变量 DEEPSEEK_API_KEY"
            )
        return key


class ASharesSourceConfig(BaseModel):
    """
    A 股数据源配置

    对应 PRD 5.1 节 data_sources.a_shares 配置

    Attributes:
        provider: A 股数据源提供商，支持 tushare 或 akshare
        token: Tushare API Token（使用 tushare 时必填）
    """

    provider: Literal["tushare", "akshare"] = "tushare"
    token: str = Field(default="", description="Tushare API Token")

    def get_token(self) -> str:
        """
        获取 Token，优先从环境变量读取

        Returns:
            str: Token

        Raises:
            ValueError: 使用 tushare 但未配置 Token
        """
        token = os.environ.get("TUSHARE_TOKEN", self.token)
        if self.provider == "tushare" and not token:
            raise ValueError(
                "使用 tushare 数据源需配置 Token。"
                "请在 config.yaml 中设置 data_sources.a_shares.token "
                "或设置环境变量 TUSHARE_TOKEN"
            )
        return token


class HKUSSourceConfig(BaseModel):
    """
    港美股数据源配置

    对应 PRD 5.1 节 data_sources.hk_us 配置

    Attributes:
        provider: 港美股数据源提供商，当前仅支持 yfinance
    """

    provider: Literal["yfinance"] = "yfinance"


class QuotesSourceConfig(BaseModel):
    """
    行情数据源配置（兼容旧版配置格式）

    Attributes:
        a_share: A 股数据源，支持 tushare 或 akshare
        hk_us: 港美股数据源，当前仅支持 yfinance
    """

    a_share: Literal["tushare", "akshare"] = "tushare"
    hk_us: Literal["yfinance"] = "yfinance"


class AShareTextSourceConfig(BaseModel):
    """
    A 股文本数据源配置

    控制各数据源的启用状态和配额权重。

    Attributes:
        enabled_sources: 启用的数据源列表
        quota_weights: 各数据源的配额权重
    """

    enabled_sources: list[Literal["research", "irm", "rating", "news"]] = Field(
        default_factory=lambda: ["research", "irm", "rating", "news"],
        description="启用的数据源列表",
    )

    quota_weights: dict[str, int] = Field(
        default_factory=lambda: {
            "research": 4,
            "irm": 3,
            "rating": 2,
            "news": 3,
        },
        description="各数据源的配额权重",
    )


class HKUSTextSourceConfig(BaseModel):
    """
    港美股文本数据源配置（预留）

    Attributes:
        search_provider: 搜索引擎提供商
        search_api_key: 搜索 API Key，留空则从环境变量读取
        trusted_domains: 可信数据源域名
    """

    search_provider: Literal["serpapi", "google_custom_search"] = Field(
        default="serpapi",
        description="搜索引擎提供商",
    )

    search_api_key: str = Field(
        default="",
        description="搜索 API Key，留空则从环境变量读取",
    )

    trusted_domains: list[str] = Field(
        default_factory=lambda: [
            "bloomberg.com",
            "reuters.com",
            "seekingalpha.com",
        ],
        description="可信数据源域名",
    )


class TextSourceConfig(BaseModel):
    """
    文本数据源配置

    Attributes:
        research_providers: 允许的研报来源机构列表
        news_sites: 允许的新闻站点列表
        search_entrypoints: 搜索入口 URL 列表
        a_share: A 股文本源配置
        hk_us: 港美股文本源配置
    """

    # 原有字段（兼容）
    research_providers: list[str] = Field(default_factory=list)
    news_sites: list[str] = Field(default_factory=list)
    search_entrypoints: list[str] = Field(default_factory=list)

    # 新增：分市场配置
    a_share: AShareTextSourceConfig = Field(
        default_factory=AShareTextSourceConfig,
        description="A 股文本源配置",
    )

    hk_us: HKUSTextSourceConfig = Field(
        default_factory=HKUSTextSourceConfig,
        description="港美股文本源配置",
    )


class TrustedSourcesConfig(BaseModel):
    """
    可信数据源配置

    对应 PRD 5.1 节 trusted_sources 配置

    Attributes:
        cn: 中文可信数据源域名列表
        en: 英文可信数据源域名列表
    """

    cn: list[str] = Field(
        default_factory=lambda: [
            "eastmoney.com",
            "10jqka.com.cn",
            "wind.com.cn",
        ],
        description="中文可信数据源",
    )
    en: list[str] = Field(
        default_factory=lambda: [
            "bloomberg.com",
            "reuters.com",
        ],
        description="英文可信数据源",
    )


class CrawlerConfig(BaseModel):
    """
    爬虫配置

    对应 PRD 5.1 节爬虫配置定义

    Attributes:
        use_mock: 开发模式，使用 Mock 假数据跳过真实数据源
        use_llm_for_sources: 是否使用 LLM 辅助生成数据源
        trusted_sources: 可信数据源配置
        lookback_hours: 文本回溯时间窗口（小时）
        max_items_per_ticker: 每个标的最大文本数量
    """

    use_mock: bool = Field(
        default=False,
        description="开发模式：使用 Mock 假数据，跳过真实数据源",
    )
    use_llm_for_sources: bool = Field(
        default=True,
        description="是否使用 LLM 辅助生成数据源",
    )
    trusted_sources: TrustedSourcesConfig = Field(
        default_factory=TrustedSourcesConfig,
        description="可信数据源配置",
    )
    lookback_hours: int = Field(
        default=48,
        gt=0,
        le=168,
        description="文本回溯时间窗口（小时）",
    )
    max_items_per_ticker: int = Field(
        default=10,
        gt=0,
        le=50,
        description="每个标的最大文本数量",
    )


class DataSourcesConfig(BaseModel):
    """
    数据源总配置

    对应 PRD 5.1 节 data_sources 配置

    Attributes:
        a_shares: A 股数据源配置（PRD 格式）
        hk_us: 港美股数据源配置（PRD 格式）
        quotes: 行情数据源配置（兼容旧格式）
        text: 文本数据源配置
        crawler: 爬虫配置
    """

    # PRD 定义的格式
    a_shares: ASharesSourceConfig = Field(
        default_factory=ASharesSourceConfig,
        description="A 股数据源配置",
    )
    hk_us: HKUSSourceConfig = Field(
        default_factory=HKUSSourceConfig,
        description="港美股数据源配置",
    )
    # 兼容旧格式
    quotes: QuotesSourceConfig = Field(default_factory=QuotesSourceConfig)
    text: TextSourceConfig = Field(default_factory=TextSourceConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)

    @model_validator(mode="after")
    def sync_quotes_config(self) -> "DataSourcesConfig":
        """同步 a_shares/hk_us 和 quotes 配置，确保兼容性"""
        # 如果 a_shares 被显式设置，同步到 quotes
        if self.a_shares.provider != "tushare":  # 非默认值
            self.quotes.a_share = self.a_shares.provider
        return self


class OutputConfig(BaseModel):
    """
    输出配置

    对应 PRD 5.1 节 output 配置

    Attributes:
        format: 输出格式，支持 csv 或 sqlite
        path: 输出文件路径
    """

    format: Literal["csv", "sqlite"] = Field(
        default="csv",
        description="输出格式",
    )
    path: str = Field(
        default="./output/audit_report.csv",
        description="输出文件路径",
    )


class TargetConfig(BaseModel):
    """
    单个监控标的配置

    Attributes:
        ticker: 证券代码，如 "601985.SH"、"0700.HK"、"AAPL"
        name: 标的名称，如 "中国核电"
        thesis: 用户对该标的的宏观/产业投资信念
        industry: 所属行业（可选）
    """

    ticker: str = Field(..., min_length=1, description="证券代码")
    name: str = Field(..., min_length=1, description="标的名称")
    thesis: str = Field(..., min_length=1, description="投资信念")
    industry: str = Field(default="未知", description="所属行业")

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        """验证并规范化 ticker 格式"""
        return v.strip().upper()

    def get_market(self) -> Literal["a_share", "hk", "us"]:
        """
        根据 ticker 后缀判断市场

        Returns:
            市场类型: "a_share", "hk", "us"
        """
        ticker = self.ticker.upper()
        if ticker.endswith((".SH", ".SZ")):
            return "a_share"
        elif ticker.endswith(".HK"):
            return "hk"
        else:
            return "us"


class SchedulerConfig(BaseModel):
    """
    调度配置

    Attributes:
        cron: cron 表达式，默认每交易日 18:00
        enabled: 是否启用调度
    """

    cron: str = "0 18 * * MON-FRI"
    enabled: bool = True


class GapThresholdConfig(BaseModel):
    """
    Gap 判定阈值配置

    根据 PRD 5.5 节定义的信号判定逻辑：
    - Gap > opportunity_gap_min 且 Sentiment < opportunity_sentiment_max → OPPORTUNITY
    - Sentiment > overheated_sentiment_min → OVERHEATED
    - 其他 → WAIT

    Attributes:
        opportunity_gap_min: 机会信号的最小 Gap 值
        opportunity_sentiment_max: 机会信号的最大情绪值
        overheated_sentiment_min: 过热信号的最小情绪值
    """

    opportunity_gap_min: float = Field(default=10.0, description="Gap > 此值视为潜在机会")
    opportunity_sentiment_max: int = Field(
        default=40, ge=0, le=100, description="情绪 < 此值视为悲观"
    )
    overheated_sentiment_min: int = Field(
        default=80, ge=0, le=100, description="情绪 > 此值视为过热"
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "GapThresholdConfig":
        """验证阈值逻辑一致性"""
        if self.opportunity_sentiment_max >= self.overheated_sentiment_min:
            raise ValueError(
                f"opportunity_sentiment_max ({self.opportunity_sentiment_max}) "
                f"应小于 overheated_sentiment_min ({self.overheated_sentiment_min})"
            )
        return self


class AppConfig(BaseModel):
    """
    应用总配置

    这是配置文件的根模型，包含所有子配置。
    对应 PRD 5.1 节完整的 config.yaml 结构。

    Attributes:
        llm_api: LLM API 配置
        data_sources: 数据源配置
        targets: 监控标的列表
        output: 输出配置
        scheduler: 调度配置
        gap_thresholds: Gap 判定阈值配置

    Example:
        >>> config = AppConfig(
        ...     targets=[
        ...         TargetConfig(
        ...             ticker="601985.SH",
        ...             name="中国核电",
        ...             thesis="AI 算力需要稳定基荷电力..."
        ...         )
        ...     ]
        ... )
    """

    llm_api: LLMConfig = Field(default_factory=LLMConfig)
    data_sources: DataSourcesConfig = Field(default_factory=DataSourcesConfig)
    targets: list[TargetConfig] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    gap_thresholds: GapThresholdConfig = Field(default_factory=GapThresholdConfig)

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, v: list[TargetConfig]) -> list[TargetConfig]:
        """验证标的列表不为空且无重复"""
        if not v:
            import warnings

            warnings.warn("targets 列表为空，没有标的可供审计")
        # 检查重复 ticker
        tickers = [t.ticker for t in v]
        if len(tickers) != len(set(tickers)):
            duplicates = [t for t in tickers if tickers.count(t) > 1]
            raise ValueError(f"存在重复的 ticker: {set(duplicates)}")
        return v

    def get_target_by_ticker(self, ticker: str) -> TargetConfig | None:
        """
        根据 ticker 获取标的配置

        Args:
            ticker: 证券代码

        Returns:
            TargetConfig | None: 标的配置，未找到返回 None
        """
        ticker = ticker.strip().upper()
        for target in self.targets:
            if target.ticker == ticker:
                return target
        return None

    def get_tickers(self) -> list[str]:
        """
        获取所有 ticker 列表

        Returns:
            list[str]: ticker 列表
        """
        return [t.ticker for t in self.targets]
