"""
配置数据模型定义

使用 Pydantic v2 定义所有配置相关的数据模型，
支持从 config.yaml 加载并进行类型验证。
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfigModel(BaseModel):
    """Base class for config sections: reject unknown keys instead of drifting."""

    model_config = ConfigDict(extra="forbid")


class LLMConfig(ConfigModel):
    """
    LLM API 配置

    Attributes:
        provider: LLM 提供商，当前仅支持 deepseek
        api_key: 兼容字段；运行期密钥只从环境变量 DEEPSEEK_API_KEY 读取
        model: 模型名称
        temperature: 温度参数，必须为 0 以保证评分稳定
        max_tokens: 最大 token 数
        max_retries: 请求失败时的最大重试次数
        thesis_thinking_enabled: 是否为 Module B（信念投影器）启用 DeepSeek 思考模式
        thesis_thinking_max_tokens: 思考模式下的最大 token 数（含思维链）
    """

    provider: Literal["deepseek"] = "deepseek"
    api_key: str = Field(
        default="",
        description="兼容字段；运行期密钥只从环境变量 DEEPSEEK_API_KEY 读取",
    )
    # `deepseek-chat` 别名 2026-07-24 退役；默认显式用 deepseek-v4-flash（当前路由目标）。
    model: str = "deepseek-v4-flash"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10, description="最大重试次数")

    # Module B 思考模式开关
    thesis_thinking_enabled: bool = Field(
        default=False,
        description="是否为 Module B（信念投影器）启用 DeepSeek 思考模式。"
        "启用后可能提升推理质量，但会增加 token 消耗和响应时间。",
    )
    thesis_thinking_max_tokens: int = Field(
        default=16384,
        gt=0,
        le=65536,
        description="思考模式下的最大 token 数（含思维链），默认 16K，最大 64K",
    )

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
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError(
                "未配置 DeepSeek API Key。"
                "请设置环境变量 DEEPSEEK_API_KEY"
            )
        return key


class ASharesSourceConfig(ConfigModel):
    """
    A 股数据源配置

    对应 PRD 5.1 节 data_sources.a_shares 配置

    Attributes:
        provider: A 股数据源提供商，支持 tushare 或 akshare
        token: 兼容字段；运行期 Token 只从环境变量 TUSHARE_TOKEN 读取
    """

    provider: Literal["tushare", "akshare"] = "tushare"
    token: str = Field(
        default="",
        description="兼容字段；运行期 Token 只从环境变量 TUSHARE_TOKEN 读取",
    )

    def get_token(self) -> str:
        """
        获取 Token，优先从环境变量读取

        Returns:
            str: Token

        Raises:
            ValueError: 使用 tushare 但未配置 Token
        """
        token = os.environ.get("TUSHARE_TOKEN")
        if self.provider == "tushare" and not token:
            raise ValueError(
                "使用 tushare 数据源需配置 Token。"
                "请设置环境变量 TUSHARE_TOKEN"
            )
        return token


class HKUSSourceConfig(ConfigModel):
    """
    港美股数据源配置

    对应 PRD 5.1 节 data_sources.hk_us 配置

    Attributes:
        provider: 港美股数据源提供商，当前仅支持 yfinance
    """

    provider: Literal["yfinance"] = "yfinance"


class QuotesSourceConfig(ConfigModel):
    """
    行情数据源配置（兼容旧版配置格式）

    Attributes:
        a_share: A 股数据源，支持 tushare 或 akshare
        hk_us: 港美股数据源，当前仅支持 yfinance
    """

    a_share: Literal["tushare", "akshare"] = "tushare"
    hk_us: Literal["yfinance"] = "yfinance"


class AShareTextSourceConfig(ConfigModel):
    """
    A 股文本数据源配置

    控制各数据源的启用状态和配额权重。

    Attributes:
        enabled_sources: 启用的数据源列表
        quota_weights: 各数据源的配额权重
    """

    enabled_sources: list[
        Literal[
            "research", "irm", "rating", "news", "announcement", "cls", "forecast"
        ]
    ] = Field(
        # #65/#66：默认扩充「公告 / 财联社」；#65：再加「盈利预测」(可达，喂 implied_growth)
        default_factory=lambda: [
            "research", "irm", "rating", "news", "announcement", "cls", "forecast"
        ],
        description="启用的数据源列表",
    )

    quota_weights: dict[str, int] = Field(
        default_factory=lambda: {
            "research": 4,
            "irm": 3,
            "rating": 2,
            "news": 3,
            "announcement": 2,
            "cls": 2,
            "forecast": 3,
        },
        description="各数据源的配额权重",
    )

    lookback_hours: int | None = Field(
        default=None,
        description=(
            "A 股文本回溯窗口覆盖（小时）；None 时沿用调用方/爬虫配置传入值。"
            "#65/#66：48h 常因太短信息不足，可调长（如 168 / 336）。"
        ),
    )

    skip_unreachable_sources: bool = Field(
        default=True,
        description=(
            "#65：本部署网络不可达的源（sina/cninfo/push2his 系，如公告/深市互动易）"
            "静默跳过并计入「未覆盖」，避免无谓超时/挂起。部署到可达网络的 P2 机器时设 False "
            "以尝试全部源。"
        ),
    )


class BrowsingConfig(ConfigModel):
    """
    多层浏览配置

    用于控制 Agent Browser 的行为，在搜索结果页发现研报链接后
    决定是否深入获取详情页内容。

    Attributes:
        enabled: 是否启用多层浏览
        max_depth: 最大浏览深度（1=仅搜索结果，2=深入一层详情页）
        max_links_per_page: 每个页面最多跟踪的链接数
        link_selection_mode: 链接选择模式 ("llm" 使用 LLM 判断, "rule" 使用规则匹配)
    """

    enabled: bool = Field(default=True, description="是否启用多层浏览")
    max_depth: int = Field(default=2, ge=1, le=3, description="最大浏览深度")
    max_links_per_page: int = Field(
        default=3, ge=1, le=10, description="每页最多跟踪链接数"
    )
    link_selection_mode: Literal["llm", "rule"] = Field(
        default="llm", description="链接选择模式"
    )


class HKUSTextSourceConfig(ConfigModel):
    """
    港美股文本数据源配置

    基于 Web Search API 获取港美股的新闻、研报等文本数据。

    Attributes:
        search_provider: 搜索服务提供商 ("serper" 推荐, "serpapi" 备选)
        search_api_key: 兼容字段；运行期密钥只从 SERPER_API_KEY / SERPAPI_KEY 读取
        browsing: 多层浏览配置
        trusted_domains: 可信域名白名单
        search_templates: 搜索查询模板
    """

    search_provider: Literal["serper", "serpapi"] = Field(
        default="serper",
        description="搜索服务提供商，推荐 serper（免费额度 2500次/月）",
    )
    search_api_key: str = Field(
        default="",
        description="兼容字段；运行期密钥只从环境变量 SERPER_API_KEY 或 SERPAPI_KEY 读取",
    )
    browsing: BrowsingConfig = Field(
        default_factory=BrowsingConfig,
        description="多层浏览配置",
    )
    trusted_domains: list[str] = Field(
        default_factory=lambda: [
            "seekingalpha.com",
            "tipranks.com",
            "morningstar.com",
            "finance.yahoo.com",
            "bloomberg.com",
            "reuters.com",
            "wsj.com",
            "ft.com",
            "cnbc.com",
            "barrons.com",
        ],
        description="可信域名白名单",
    )
    search_templates: dict[str, str] = Field(
        default_factory=lambda: {
            "research": "{ticker} {name} analyst report research",
            "news": "{ticker} {name} news",
            "earnings": "{ticker} earnings analysis",
        },
        description="搜索查询模板，支持 {ticker} 和 {name} 占位符",
    )


class TextSourceConfig(ConfigModel):
    """
    文本数据源配置

    按市场类型分别配置文本数据获取策略。

    Attributes:
        a_share: A 股文本源配置（基于 AkShare API）
        hk_us: 港美股文本源配置（基于 Web Search，预留）
    """

    a_share: AShareTextSourceConfig = Field(
        default_factory=AShareTextSourceConfig,
        description="A 股文本源配置",
    )

    hk_us: HKUSTextSourceConfig = Field(
        default_factory=HKUSTextSourceConfig,
        description="港美股文本源配置",
    )

    @model_validator(mode="before")
    @classmethod
    def warn_deprecated_fields(cls, data: dict) -> dict:
        """向后兼容：警告并忽略已废弃的配置字段"""
        if not isinstance(data, dict):
            return data

        import warnings

        deprecated = ["research_providers", "news_sites", "search_entrypoints"]
        found = [f for f in deprecated if f in data]
        if found:
            warnings.warn(
                f"配置字段 {found} 已废弃，将被忽略。"
                f"A 股文本数据现在通过 AkShare API 获取，请使用 'a_share' 配置。",
                DeprecationWarning,
                stacklevel=2,
            )
            # 删除旧字段，避免 Pydantic 报错
            for f in found:
                data.pop(f, None)
        return data


class TrustedSourcesConfig(ConfigModel):
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


class CrawlerConfig(ConfigModel):
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
        le=8760,
        description="文本回溯时间窗口（小时）",
    )
    max_items_per_ticker: int = Field(
        default=10,
        gt=0,
        le=200,
        description="每个标的最大文本数量",
    )


class DataSourcesConfig(ConfigModel):
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


class OutputConfig(ConfigModel):
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
    artifacts_dir: str = Field(
        default="./output/artifacts",
        description="S1–S5 阶段产物（RefinedThesis/LogicChain/Evidence/...）的 JSON 持久化目录",
    )


class PersistenceConfig(ConfigModel):
    """持久化后端配置（P2：决策日志 / 持仓 / 风控史 / alpha 同库 SQLite）。

    对应 D-20260629-1（持久化=SQLite）与 S7 决策日志（CDX-2）落地：

    Attributes:
        backend: 持久化后端。``csv``（默认）仅写 ``output`` 的审计报告 CSV；
            ``sqlite`` 在此之上把每笔 S7 决策（含 WAIT）落进决策日志 SQLite。
        sqlite_path: SQLite DB 文件路径（``backend=sqlite`` 时生效）。
    """

    backend: Literal["csv", "sqlite"] = Field(
        default="csv",
        description="持久化后端：csv 仅写审计报告；sqlite 额外写 S7 决策日志",
    )
    sqlite_path: str = Field(
        default="data/alice.db",
        description="决策日志 SQLite DB 文件路径（backend=sqlite 时生效）",
    )


class TargetConfig(ConfigModel):
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


class SchedulerConfig(ConfigModel):
    """
    调度配置

    Attributes:
        cron: cron 表达式，默认每交易日 18:00
        enabled: 是否启用调度
    """

    cron: str = "0 18 * * MON-FRI"
    enabled: bool = True


class GapThresholdConfig(ConfigModel):
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


class FinancialAnalysisConfig(ConfigModel):
    """S4 财务分析配置"""

    enabled: bool = Field(
        default=True, description="是否启用 S4 财报/估值分析（关闭则定量环节转尽调）"
    )
    use_mock: bool = Field(
        default=False,
        description="开发/离线模式：用 MockFinancialsProvider 假财报。独立于文本 use_mock。",
    )


class PipelineConfig(ConfigModel):
    """S1–S5 多阶段信念流水线配置"""

    enabled: bool = Field(
        default=True,
        description="True: 用多阶段 ThesisPipeline（默认）；False: 回退单次 ThesisProjector",
    )


class RiskControlConfig(ConfigModel):
    """S6 组合层风控配置（pydantic 版，镜像 engines.risk_engine.RiskConfig）。

    阈值均可在 config.yaml 的 `risk:` 段覆盖；main.py 将其映射为引擎侧
    `RiskConfig` 数据类后注入 `RiskEngine`。v0.1 仅用到 sizing_mode="equal"
    占位，conviction / risk_budget 待 6/28 会议 D1 定后启用。
    """

    ref_weight: float = Field(
        default=0.05, ge=0.0, le=1.0, description="单笔软参考权重（非硬顶）"
    )
    soft_cap: float = Field(
        default=0.10, ge=0.0, le=1.0, description="单笔软护栏（可被风险预算进一步压低）"
    )
    target_positions: int = Field(
        default=20, gt=0, le=500, description="目标持仓数（~20 × 5% ≈ 满仓）"
    )
    max_cluster_weight: float = Field(
        default=0.15, ge=0.0, le=1.0, description="同簇（行业/主题）合计权重上限"
    )
    total_risk_budget: float = Field(
        default=1.0, ge=0.0, le=1.0, description="组合总投入上限（1.0=可满仓；现金=1-Σw）"
    )
    sizing_mode: Literal["equal", "conviction", "risk_budget"] = Field(
        default="equal",
        description="v0.1 仅 equal 生效；conviction / risk_budget 待 D1 定后启用",
    )
    enabled: bool = Field(
        default=True, description="是否启用 S6 组合层风控叠加（关闭则不回填风控字段）"
    )


class AppConfig(ConfigModel):
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
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    financial_analysis: FinancialAnalysisConfig = Field(
        default_factory=FinancialAnalysisConfig
    )
    risk: RiskControlConfig = Field(default_factory=RiskControlConfig)
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
