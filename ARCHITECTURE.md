# Alice Test - 系统架构设计

## 1. 推荐目录结构

```
alice_test/
├── src/
│   ├── __init__.py
│   ├── main.py                      # 程序入口（逐标的流水线 + S6 组合叠加 + S7 决策日志接线）
│   │
│   ├── config/                      # 配置管理模块
│   │   ├── __init__.py
│   │   ├── manager.py               # ConfigManager 配置加载器
│   │   ├── models.py                # 配置数据模型
│   │   └── env_interpolation.py     # ${ENV} 占位插值（缺失 fail-closed；密钥不驻留 AppConfig）
│   │
│   ├── data_ingestion/              # 数据摄入模块
│   │   ├── __init__.py
│   │   ├── models.py                # TickerRawData, TextItem 数据模型
│   │   ├── quotes/                  # 行情数据采集（base / tushare / akshare / yfinance / fallback 降级）
│   │   ├── text/                    # 文本数据采集（factory 路由；a_share/ + hk_us/ + akshare/ + mock_provider）
│   │   ├── financials/              # S4 财报/盈利预测采集（A股 AkShare|Tushare；港美 yfinance；mock 离线）
│   │   └── preprocessor.py          # 文本去噪与过滤
│   │
│   ├── engines/                     # 核心引擎模块
│   │   ├── __init__.py
│   │   ├── consensus_engine.py      # Module A: 市场共识引擎
│   │   ├── thesis_projector.py      # Module B: 信念投影器
│   │   ├── thesis_pipeline.py       # S1–S5 多阶段命题流水线（S2 拆解后自查补漏，#87）
│   │   ├── financial_analysis.py    # S4: 财务证据 / 估值反推
│   │   ├── gap_calculator.py        # Gap 计算与信号判定
│   │   ├── risk_engine.py           # S6: 组合风控叠加（纯数学、无 LLM，见 §3.5）
│   │   ├── proxy_library.py         # S3 proxy 备选库加载/校验/渲染（#87，fail-closed）
│   │   └── resources/
│   │       └── proxy_library.yaml   # 包内默认备选库（config.proxy_library.path 可覆盖）
│   │
│   ├── llm/                         # LLM 封装模块
│   │   ├── __init__.py
│   │   ├── deepseek_client.py       # DeepSeek API 客户端（per-stage thinking/effort，见 §3.1）
│   │   ├── prompts.py               # Prompt 模板管理
│   │   └── models.py                # LLM 响应数据模型
│   │
│   ├── persistence/                 # 持久化模块
│   │   ├── __init__.py
│   │   ├── base.py                  # 存储抽象接口
│   │   ├── csv_writer.py            # CSV 实现
│   │   ├── sqlite_store.py          # SQLite：审计报告 + S7 决策日志（#81 落地，见 §3.6）
│   │   └── artifact_store.py        # 阶段产物 JSON 存储（证据链工件）
│   │
│   ├── reporting/                   # 报告模块
│   │   ├── __init__.py
│   │   └── daily_report.py          # 自包含 HTML 日报（#88；零 LLM/零网络，不写业务数据；打开旧库自动补列迁移）
│   │
│   └── utils/                       # 工具模块
│       ├── __init__.py
│       ├── logger.py                # 日志工具
│       └── sanitizer.py             # LLM 前文本脱敏（防内容审核误伤）
│
├── config.yaml                      # 配置文件
├── audit_report.csv                 # 审计报告输出
├── requirements.txt
└── README.md
```

## 2. 模块职责说明

| 模块 | 职责 |
|------|------|
| `config/` | 加载并解析 config.yaml，提供类型安全的配置对象；`${ENV}` 占位插值（缺失即错、密钥不驻留） |
| `data_ingestion/quotes/` | 从 Tushare/AkShare/yfinance 获取行情数据（含不可达源降级） |
| `data_ingestion/text/` | 按市场路由采集研报/新闻文本，限定在配置的权威来源内；mock provider 供离线开发 |
| `data_ingestion/financials/` | S4 财报与盈利预测数据（A股东财免 token 接口 / 港美 yfinance / mock） |
| `data_ingestion/preprocessor.py` | 文本去噪、正则过滤、保留有观点密度的内容 |
| `engines/consensus_engine.py` | 调用 LLM 提取市场共识、情绪评分、隐含增长率 |
| `engines/thesis_projector.py` | 调用 LLM 基于用户宏观信念评估合理增长率 |
| `engines/thesis_pipeline.py` | S1–S5：命题完善 → 逻辑链拆解（含拆解后自查补漏，#87）→ proxy 映射 → 证据/估值反推 → 信念综合 |
| `engines/financial_analysis.py` | S4 财务证据分析与估值反推（配合 financials/ 数据） |
| `engines/gap_calculator.py` | 本地计算 Gap 值，生成 OPPORTUNITY/OVERHEATED/WAIT 信号 |
| `engines/risk_engine.py` | S6 组合风控叠加：软参考 sizing + 行业聚类上限 + 总风险预算（纯数学、离线确定性可测） |
| `engines/proxy_library.py` | S3 proxy 备选库（#87）：加载/校验备选库 yaml 并渲染进 S3 系统指令，提案从「LLM 从零发明」变「库中选型 + 允许补充」；fail-closed、库⇔词表加载期一致性、`enabled=False` 逐字回归无库 prompt |
| `llm/deepseek_client.py` | 封装 DeepSeek API 调用、重试机制、JSON 解析；per-stage thinking/effort 与非 thinking 路径 temp=0 硬锁 |
| `llm/prompts.py` | 管理 Consensus Engine 和 Thesis Projector 的 Prompt 模板 |
| `persistence/` | 审计结果写 CSV/SQLite（追加模式）；S7 决策日志（`SQLiteStore`）；阶段产物工件（`ArtifactStore`） |
| `reporting/daily_report.py` | 自包含 HTML 日报（#88）：从决策日志 SQLite 生成单文件日报（当日决策 + coverage 四计数 + 累计 hit_rate/IC + 尽调队列 + 确定性 Bottom line）；零 LLM、零网络、同输入同字节；不写业务数据，但经 `SQLiteStore` 打开旧版库会触发补列迁移（只读快照上会失败） |
| `utils/logger.py` | 统一日志格式，记录运行统计信息 |
| `utils/sanitizer.py` | LLM 调用前文本脱敏，避免触发内容审核 |

## 3. 关键类和接口定义汇总

### 3.1 配置模块 (`config/`)

```python
# config/models.py
@dataclass
class LLMConfig:
    provider: Literal["deepseek"]
    api_key: str             # 不驻留：getter 运行期读 env / 解析 ${ENV} 占位
    model: str               # 非 thinking 路径（v4-flash）
    model_pro: str           # thinking 深推理路径（v4-pro）
    temperature: float       # 非 thinking 路径硬锁 0（非 0 报错）；thinking 路径 no-op
    max_tokens: int
    reasoning_effort: Literal["high", "max"]  # thinking 路径 effort；默认 high
    thesis_thinking_enabled: bool             # 驱动 Module B / S5 thinking

@dataclass
class TargetConfig:
    ticker: str      # 证券代码，如 "601985.SH"
    name: str        # 标的名称
    thesis: str      # 用户宏观信念

@dataclass
class AppConfig:
    llm_api: LLMConfig
    data_sources: DataSourcesConfig
    targets: list[TargetConfig]
    scheduler: SchedulerConfig
    gap_thresholds: GapThresholdConfig

# config/manager.py
class ConfigManager:
    def __init__(self, config_path: str | Path | None = None): ...
    def load(self) -> AppConfig: ...
    def get_api_key(self) -> str: ...
    def get_targets(self) -> list[TargetConfig]: ...
```

### 3.2 数据摄入模块 (`data_ingestion/`)

```python
# data_ingestion/models.py
@dataclass
class TextItem:
    source: str                        # 券商/媒体名称
    type: Literal["research", "news"]  # 文本类型
    title: str
    summary: str
    published_at: datetime
    url: str | None = None

@dataclass
class QuoteData:
    date: datetime
    ticker: str
    price_close: float
    pe_ttm: float | None
    pb: float | None
    turnover_rate: float | None

@dataclass
class TickerRawData:
    date: datetime
    ticker: str
    name: str
    quote: QuoteData
    texts: list[TextItem]
    status: Literal["ok", "data_error", "partial"]

# data_ingestion/quotes/base.py
class QuotesProvider(ABC):
    @abstractmethod
    def get_quote(self, ticker: str, date: datetime | None = None) -> QuoteData: ...
    @abstractmethod
    def get_historical_quotes(self, ticker: str, start_date: datetime, end_date: datetime) -> list[QuoteData]: ...
    @abstractmethod
    def is_market_supported(self, ticker: str) -> bool: ...

# data_ingestion/text/base.py
class TextProvider(ABC):
    @abstractmethod
    def fetch_texts(self, ticker: str, name: str, lookback_hours: int = 48, max_items: int = 10) -> list[TextItem]: ...
    @abstractmethod
    def get_source_name(self) -> str: ...

# data_ingestion/preprocessor.py
class TextPreprocessor:
    def filter_texts(self, texts: list[TextItem], max_items: int = 10) -> list[TextItem]: ...
    def is_noise(self, text: TextItem) -> bool: ...
    def extract_key_content(self, raw_text: str) -> str: ...
    def calculate_opinion_density(self, text: TextItem) -> float: ...

# config/models.py - 爬虫配置
class CrawlerConfig:
    use_llm_for_sources: bool = True           # 是否使用 LLM 辅助生成数据源
    trusted_sources: TrustedSourcesConfig      # 可信数据源配置
    lookback_hours: int = 48                   # 文本回溯时间窗口（小时）
    max_items_per_ticker: int = 10             # 每个标的最大文本数量

class TrustedSourcesConfig:
    cn: list[str]  # 中文可信源: eastmoney.com, 10jqka.com.cn, wind.com.cn
    en: list[str]  # 英文可信源: bloomberg.com, reuters.com
```

### 3.3 LLM 模块 (`llm/`)

```python
# config/models.py - LLM 配置
class LLMConfig(BaseModel):
    provider: Literal["deepseek"] = "deepseek"
    api_key: str = ""                          # 不驻留：getter 读 env / 解析 ${ENV} 占位
    model: str = "deepseek-v4-flash"           # 非 thinking 打分/汇总路径
    model_pro: str = "deepseek-v4-pro"         # thinking 深推理路径（S1/S2/S4/S5/B）
    temperature: float = 0.0                   # 非 thinking 路径硬锁 0；thinking 路径 no-op
    max_tokens: int = 4096
    max_retries: int = 2
    reasoning_effort: Literal["high", "max"] = "high"  # thinking 路径 effort

    # thinking 模式配置（驱动 Module B / S5）
    thesis_thinking_enabled: bool = False      # 是否启用思考模式
    thesis_thinking_max_tokens: int = 16384    # 思考模式最大 token 数
```

#### 模型 / thinking / effort 按阶段分流

按阶段分流（迁移计划 §4），不一刀切：

- **非 thinking 路径**（Module A 打分、S3、S7）：`model`（v4-flash）+ 客户端显式
  `thinking: disabled` + `temperature=0` 硬锁——保证评分逐位可复现。v4 系列模型级
  thinking 默认开启，不显式关闭会被静默拉进 thinking、temperature 被忽略（已真调用核实）。
- **thinking 路径**（目标 S1/S2/S4/S5、Module B/S5）：`model_pro`（v4-pro）+ `thinking: enabled`
  + `reasoning_effort`（默认 high，最难的 S4 / 必要时 S5 开 max）。temperature 为 no-op，
  复现性改由硬编码量表 + JSON schema 保证。

> **现状（本期接线）**：以上为迁移目标矩阵。当前 `DeepSeekClient` 仅 `get_thesis_synthesis`（S5）
> 与 `get_thesis_projection`（Module B）以 `use_thinking=thesis_thinking_enabled` 启用 thinking；
> `reasoning_effort` 为客户端级默认（`high`），`chat()` 支持 per-call 覆盖但 S1–S4 调用点尚未接线
> （待迁移计划 Q2/Q3 拍板）。S1–S4、Module A、S3、S7 当前均走非 thinking + v4-flash 路径。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `model` | 非 thinking 路径模型 | `deepseek-v4-flash` |
| `model_pro` | thinking 路径模型 | `deepseek-v4-pro` |
| `reasoning_effort` | thinking 路径 effort（high\|max） | `high` |
| `thesis_thinking_enabled` | 是否为 Module B / S5 启用思考模式 | `false` |
| `thesis_thinking_max_tokens` | 思考模式最大 token 数 | `16384` |

> 密钥不驻留：`api_key` / `token` 等密钥字段绝不进 `dump` / `repr` / 日志；可留空（运行期读固定
> env）或写 `${ENV}` 占位（getter 运行期即时解析、不写回配置）。`${ENV}` 占位对非密钥字段在
> load 时解析，引用缺失即 fail-closed 报错。

**使用建议：**
- 初期建议保持关闭（`false`），使用标准模式
- 如发现增长率预估准确性不足，可开启进行对比测试
- 思考模式会增加约 2-3 倍的 token 消耗和响应时间

```python
# llm/models.py
@dataclass
class ConsensusResult:
    """Module A 输出 - 对应 PRD 4.2.2"""
    sentiment_score: int       # 0-100 情绪评分
    sentiment_label: str       # 恐慌|悲观|中性|乐观|狂热
    implied_growth: float      # 百分数，如 5.0 表示 5%
    key_narrative: str         # 一句话市场总结
    key_worry: str             # 主要担忧
    key_hope: str              # 主要期待
    def validate(self) -> bool: ...

@dataclass
class ThesisProjectionResult:
    """Module B 输出 - 对应 PRD 4.3.1"""
    thesis_aligned: bool       # 是否与用户信念一致
    our_growth: float          # 百分数，如 15.0 表示 15%
    confidence: str            # 高|中|低
    reasoning: str             # 2-3 句解释
    def validate(self) -> bool: ...

# llm/deepseek_client.py
class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        model: str | None = None,          # 非 thinking 路径模型
        temperature: float | None = None,
        max_tokens: int | None = None,
        base_url: str = "https://api.deepseek.com",
        thinking_enabled: bool = False,
        thinking_max_tokens: int | None = None,
        model_pro: str | None = None,      # thinking 路径模型（回退到 model）
        reasoning_effort: str | None = None,  # thinking effort（high|max）
    ): ...

    # use_thinking=True → 走 model_pro + thinking enabled + reasoning_effort（可按调用覆盖）；
    # use_thinking=False → 走 model + 显式 thinking disabled + temperature。
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        use_thinking: bool = False,
        reasoning_effort: str | None = None,
    ) -> LLMResponse: ...

    def chat_with_json_output(
        self,
        system_prompt: str,
        user_prompt: str,
        result_class: Type[T],
        max_retries: int | None = None,
        use_thinking: bool = False,
        reasoning_effort: str | None = None,
    ) -> T: ...

    def get_consensus(
        self,
        ticker: str,
        ticker_name: str,
        price_close: float,
        pe_ttm: float | None,
        pb: float | None,
        texts_content: str,
    ) -> ConsensusResult: ...

    def get_thesis_projection(
        self,
        ticker: str,
        ticker_name: str,
        user_thesis: str,
        industry: str = "未知",
    ) -> ThesisProjectionResult: ...

# llm/prompts.py
class PromptTemplates:
    CONSENSUS_ENGINE_SYSTEM: str   # Module A System Prompt
    CONSENSUS_ENGINE_USER: str     # Module A User Prompt
    THESIS_PROJECTOR_SYSTEM: str   # Module B System Prompt
    THESIS_PROJECTOR_USER: str     # Module B User Prompt

    @classmethod
    def format_consensus_prompt(...) -> tuple[str, str]: ...
    @classmethod
    def format_thesis_prompt(...) -> tuple[str, str]: ...
```

### 3.4 引擎模块 (`engines/`)

```python
# engines/consensus_engine.py
class ConsensusEngine:
    """Module A: 市场共识引擎"""
    def __init__(self, llm_client: DeepSeekClient): ...
    def analyze(self, raw_data: TickerRawData) -> ConsensusResult: ...

# engines/thesis_projector.py
class ThesisProjector:
    """Module B: 信念投影器"""
    def __init__(self, llm_client: DeepSeekClient): ...
    def project(self, target: TargetConfig, industry: str = "未知") -> ThesisProjectionResult: ...
    def project_batch(self, targets: list[TargetConfig]) -> dict[str, ThesisProjectionResult]: ...

# engines/gap_calculator.py
class AuditSignal(str, Enum):
    OPPORTUNITY = "OPPORTUNITY"
    OVERHEATED = "OVERHEATED"
    WAIT = "WAIT"

@dataclass
class AuditResult:
    """审计结果 - 对应 PRD 6.1 audit_report.csv 字段定义"""
    # 基础信息
    date: datetime           # 审计日期 (YYYY-MM-DD)
    ticker: str              # 股票代码
    name: str                # 公司名称
    price: float             # 收盘价
    pe_ttm: float | None     # 市盈率（TTM）

    # Module A 输出
    sentiment_score: int     # 情绪分数 (0-100)
    sentiment_label: str     # 情绪标签 (恐慌|悲观|中性|乐观|狂热)
    implied_growth: float    # 市场隐含增长率 %
    key_narrative: str       # 一句话市场总结
    key_worry: str           # 主要担忧
    key_hope: str            # 主要期待

    # Module B 输出
    thesis_aligned: bool     # 是否与投资信念一致
    our_growth: float        # 信念预期增长率 %
    confidence: str          # 预测置信度 (高|中|低)
    reasoning: str           # 信念投影推理说明

    # 信号判定
    gap: float               # 认知差 (our - implied)
    signal: AuditSignal      # OPPORTUNITY / OVERHEATED / WAIT
    sentiment_overheat: bool # v2：情绪过热 flag（只登记、不参与信号；S6 追加 SENTIMENT_OVERHEAT）
    status: Literal["ok", "data_error", "llm_error"]

class GapCalculator:
    def __init__(self, thresholds: GapThresholdConfig | None = None): ...
    def calculate_gap(self, our_growth: float, implied_growth: float) -> float: ...
    def determine_signal(self, gap: float) -> AuditSignal: ...       # v2：只吃 gap（α 差双向）
    def is_sentiment_overheat(self, sentiment_score: int) -> bool: ...
    def compute_audit_result(
        self,
        ticker: str,
        name: str,
        price: float,
        pe_ttm: float | None,
        consensus: ConsensusResult,
        thesis_projection: ThesisProjectionResult,
        audit_date: datetime | None = None,
    ) -> AuditResult: ...
```

### 3.5 S6 风控引擎 (`engines/risk_engine.py`)

```python
# 纯数学、无 LLM、离线确定性可测（#76 接入流水线）
@dataclass
class RiskConfig:      # ref_weight / soft_cap / target_positions / max_cluster_weight / total_risk_budget / sizing_mode
@dataclass
class RiskAssessment:  # 单标的评估：建议权重、risk_adjusted_action (BUY/TRIM/WAIT/EXIT/AVOID)、证伪条件等
@dataclass
class PortfolioState:  # 组合状态（v0.1 greenfield 空仓起步）

class RiskEngine:
    def assess_one(self, item: AuditLike) -> RiskAssessment: ...
    def assess_portfolio(self, items) -> list[RiskAssessment]: ...
    # 跨标的第二遍：等权软参考 → 行业聚类上限（空/未知行业归 UNKNOWN）→ 总风险预算缩放
    # 资格门 _eligible = signal==OPPORTUNITY 且 thesis_aligned
```

v0.1 语义（decision-free）：输出是**软参考**，单笔不设硬顶；「买/多大仓」仍由 S7 人工拍板。信号语义 v2（D-20260705-1）：OVERHEATED（负 α）→ `AVOID`（不进场、weight=0，计入 actionable）；`sentiment_overheat` flag 由 S6 以 `SENTIMENT_OVERHEAT` 登记进 `correlation_flags`（只登记，不折减权重——折减系数未拍）。SHORT 零代码路径（做空=远期规划，2026-07-08 澄清，届时另拍）。

### 3.6 持久化模块 (`persistence/`)

```python
# persistence/base.py
class AuditReportStore(ABC):
    @abstractmethod
    def save(self, result: AuditResult) -> None: ...
    @abstractmethod
    def save_batch(self, results: list[AuditResult]) -> None: ...
    @abstractmethod
    def get_by_ticker(self, ticker: str, start_date: datetime | None = None, end_date: datetime | None = None) -> list[AuditResult]: ...
    @abstractmethod
    def get_by_date(self, date: datetime) -> list[AuditResult]: ...
    @abstractmethod
    def get_by_signal(self, signal: str, start_date: datetime | None = None, end_date: datetime | None = None) -> list[AuditResult]: ...
    @abstractmethod
    def get_latest(self, ticker: str) -> AuditResult | None: ...

# persistence/csv_writer.py
class CSVReportWriter(AuditReportStore):
    CSV_COLUMNS: list[str]  # ["Date", "Ticker", "Name", "Price", ...]
    def __init__(self, file_path: str | Path = "audit_report.csv"): ...
    # 实现所有抽象方法

# persistence/sqlite_store.py —— #81 已完整落地（不再是预留桩）
class SQLiteReportStore(AuditReportStore):
    """审计报告的 SQLite 后端（与 CSVReportWriter 同接口）"""
    def __init__(self, db_path: str | Path = "audit_data.db"): ...

# S7 决策日志（CDX-2 终态）；config.persistence.backend="sqlite" 时由 main 接线写入
@dataclass
class DecisionEntry: ...   # decision_id = f"{ticker}-{asof_date}"；缺数据留 NULL，不造数
@dataclass
class OutcomeEntry: ...    # created_at 由 store 时钟盖戳，调用方不可倒填

class SQLiteStore:
    # 表：decision_log / decision_outcome / position_history / alpha_track（后两者写方法 = v0.2）
    # decision_log 附加列：signal_semantics（v2 标记，#86）；cov_links_total/quant/evidenced/dd
    #   （coverage 四计数，#88）——均可空，旧库 ADD COLUMN、旧行保持 NULL 不回填（append-only）
    def save_decision(self, entry) -> str: ...        # 幂等 upsert
    def record_outcome(self, outcome) -> int: ...     # append-only
    def get_decisions(self, asof=None, ...): ...      # point-in-time 按 created_at（存在性快照，非内容版本化）
    def get_open_decisions(self, asof=None): ...
    def hit_rate(self, since=None, until=None, horizon=None, asof=None): ...
    def information_coefficient(self, predictor="gap", ...): ...  # 与 hit_rate 同源窗口/PIT 口径
```

### 3.7 主程序 (`main.py`)

```python
class AliceTestPipeline:
    def __init__(self, config: AppConfig): ...
    def run(self) -> list[AuditResult]: ...   # 逐标的流水线 → S6 组合叠加（第二遍）→ S7 决策日志
    def _process_single_target(self, target: TargetConfig) -> AuditResult: ...
    def _ingest_data(self, target: TargetConfig) -> TickerRawData: ...
    def _build_risk_engine(self) -> RiskEngine | None: ...   # config.risk.enabled=False → 跳过叠加
    def _build_decision_entry(self, result) -> DecisionEntry: ...
    def _coverage_counts(pr) -> tuple[int | None, ...]: ...  # 证据链完成度四计数（#88，纯审计指标；回退/fail-closed 行全 None，不造 0）
    def _write_daily_report_html(self, results) -> None: ... # output.daily_report_html=true 时的可选钩子（#88，默认关）
    # 决策日志覆盖所有结果（含 WAIT 与 fail-closed）；回退 BUY 门控 = OPPORTUNITY 且 thesis_aligned

def main() -> None:
    """命令行入口: python -m src.main --config config.yaml"""
    ...

# 日报独立 CLI（#88；box cron 推荐在 daily-run 后链式调用，零 LLM、不写业务数据；旧库会被自动补列迁移）：
#   python -m src.reporting.daily_report --config config.yaml [--date YYYY-MM-DD] [--out DIR]
```

## 4. 数据流图

```
┌─────────────────┐
│   config.yaml   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ConfigManager   │ ──▶ AppConfig
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    AliceTestPipeline                        │
│  ┌────────────────┐    ┌────────────────┐                   │
│  │ QuotesProvider │    │  TextProvider  │                   │
│  │  (行情数据)     │    │   (文本数据)    │                   │
│  └───────┬────────┘    └───────┬────────┘                   │
│          │                     │                            │
│          └─────────┬───────────┘                            │
│                    ▼                                        │
│          ┌─────────────────┐                                │
│          │ TextPreprocessor│                                │
│          │   (文本去噪)     │                                │
│          └────────┬────────┘                                │
│                   ▼                                         │
│          ┌─────────────────┐                                │
│          │ TickerRawData   │                                │
│          └────────┬────────┘                                │
│                   │                                         │
│     ┌─────────────┼─────────────┐                           │
│     ▼             │             ▼                           │
│ ┌────────────┐    │    ┌─────────────────┐                  │
│ │ Consensus  │    │    │ ThesisProjector │                  │
│ │  Engine    │    │    │    (Module B)   │                  │
│ │ (Module A) │    │    └────────┬────────┘                  │
│ └─────┬──────┘    │             │                           │
│       │           │             │                           │
│       ▼           │             ▼                           │
│ ConsensusResult   │    ThesisProjectionResult               │
│       │           │             │                           │
│       └─────────┬─┴─────────────┘                           │
│                 ▼                                           │
│        ┌─────────────────┐                                  │
│        │  GapCalculator  │                                  │
│        └────────┬────────┘                                  │
│                 ▼                                           │
│           AuditResult (逐标的)                               │
└─────────────────┬───────────────────────────────────────────┘
                  │ 全部标的完成后
                  ▼
         ┌─────────────────┐
         │   RiskEngine    │  S6 跨标的第二遍（#76）：
         │   (组合叠加)     │  软参考权重 + 聚类上限 + 总预算
         └────────┬────────┘  → risk_adjusted_action
                  │
        ┌─────────┴──────────────┐
        ▼                        ▼
┌─────────────────┐   ┌───────────────────────┐
│ AuditReportStore│   │ SQLiteStore 决策日志   │
│ csv / sqlite    │   │ decision_log / outcome │
└─────────────────┘   └───────────────────────┘
                        (backend=sqlite 时写入；
                         覆盖 WAIT 与 fail-closed)
```

## 5. 信号判定逻辑（v2：纯 α 差双向触发）

拍板：**D-20260627-P0-1**（废止 v1「gap+sentiment 双条件」旧门）、**D-20260627-CDX-1**（α = our growth − market growth；sentiment 不单独产 α、不纯做 veto）、**D-20260705-1**（OVERHEATED = 相对我方 thesis 模型的负 α，计入 actionable/IC）。2026-07-08 落地。

```python
# 信号语义 v2（determine_signal 只吃 gap）
if gap > opportunity_gap_min:        # 默认 10
    signal = "OPPORTUNITY"   # 正 α：市场定价低于我方模型
elif gap < -overheated_gap_min:      # 默认 10（与 opportunity 对称；数值未专门拍）
    signal = "OVERHEATED"    # 负 α：市场 implied 定价高于我方模型 → 动作 AVOID（不进场）
else:
    signal = "WAIT"          # 含 gap=NaN（fail-closed 行）
```

- sentiment 摘出信号门：`sentiment_score > 80` 只产 `sentiment_overheat` flag（S6 登记 `SENTIMENT_OVERHEAT`，不折减权重）。
- OVERHEATED → `AVOID`：suggested_weight=0、计入 actionable；hit(AVOID) = excess_return < 0。持仓感知 TRIM/SELL 待 position_history（v0.2）。SHORT 零代码路径（远期另拍）。
- 决策日志新行带 `signal_semantics='v2'`；旧行 NULL 视为 v1，append-only 不回写。

阈值来自 `config.yaml` 的 `gap_thresholds`（代码默认 = 上述标准值；v1 情绪字段 deprecated，兼容加载）。

## 6. 实现状态与后续优先级（2026-07-22）

**已完成**：MVP 全链路 + S1–S5 命题流水线（P1）、S6 风控叠加（#76）、fail-closed 不造数 / 外部文本围栏 / temperature=0 硬锁（#77–#80）、S7 决策日志 SQLite（#81）、LLM per-stage 基建 + `${ENV}` 插值（#82）、SOURCE_REACHABILITY 按 box 实测更新（#84/CDX-6）、LLM 用量统计接线（#85）、信号语义 v2（#86，D-20260705-1，见 §5）、S3 proxy 备选库 + S2 拆链补漏自查（#87）、coverage 四计数 + 自包含 HTML 日报（#88）。

**下一步**（权威清单见团队内部 ItemList / 决策台账）：

1. daily-run 自动化（cron 化入口）—— P0-5 验证起跑的最后前置；#88 已落地日报侧（`output.daily_report_html` 钩子 + `python -m src.reporting.daily_report` CLI），box 侧 cron 接线待做
2. LLM per-stage 剩余接线（S1–S4 thinking、effort=max 范围）待拍
3. S7 v0.2：versioned rows（内容级 point-in-time）、`position_history` / `alpha_track` 写方法、跨日改写护栏
