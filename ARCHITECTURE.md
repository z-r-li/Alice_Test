# Alice Test - 系统架构设计

## 1. 推荐目录结构

```
alice_test/
├── src/
│   ├── __init__.py
│   ├── main.py                      # 程序入口
│   │
│   ├── config/                      # 配置管理模块
│   │   ├── __init__.py
│   │   ├── manager.py               # ConfigManager 配置加载器
│   │   └── models.py                # 配置数据模型
│   │
│   ├── data_ingestion/              # 数据摄入模块
│   │   ├── __init__.py
│   │   ├── models.py                # TickerRawData, TextItem 数据模型
│   │   ├── quotes/                  # 行情数据采集
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # QuotesProvider 抽象基类
│   │   │   ├── tushare_client.py    # Tushare 实现 (A股)
│   │   │   ├── akshare_client.py    # AkShare 实现 (A股备选)
│   │   │   └── yfinance_client.py   # yfinance 实现 (港/美股)
│   │   ├── text/                    # 文本数据采集
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # TextProvider 抽象基类
│   │   │   ├── research_crawler.py  # 研报爬虫
│   │   │   └── news_crawler.py      # 新闻爬虫
│   │   └── preprocessor.py          # 文本去噪与过滤
│   │
│   ├── engines/                     # 核心引擎模块
│   │   ├── __init__.py
│   │   ├── consensus_engine.py      # Module A: 市场共识引擎
│   │   ├── thesis_projector.py      # Module B: 信念投影器
│   │   └── gap_calculator.py        # Gap 计算与信号判定
│   │
│   ├── llm/                         # LLM 封装模块
│   │   ├── __init__.py
│   │   ├── deepseek_client.py       # DeepSeek API 客户端
│   │   ├── prompts.py               # Prompt 模板管理
│   │   └── models.py                # LLM 响应数据模型
│   │
│   ├── persistence/                 # 持久化模块
│   │   ├── __init__.py
│   │   ├── base.py                  # 存储抽象接口
│   │   ├── csv_writer.py            # CSV 实现
│   │   └── sqlite_store.py          # SQLite 实现 (预留)
│   │
│   └── utils/                       # 工具模块
│       ├── __init__.py
│       └── logger.py                # 日志工具
│
├── config.yaml                      # 配置文件
├── audit_report.csv                 # 审计报告输出
├── requirements.txt
└── README.md
```

## 2. 模块职责说明

| 模块 | 职责 |
|------|------|
| `config/` | 加载并解析 config.yaml，提供类型安全的配置对象 |
| `data_ingestion/quotes/` | 从 Tushare/AkShare/yfinance 获取行情数据 |
| `data_ingestion/text/` | 爬取研报摘要、新闻标题，限定在配置的权威来源内 |
| `data_ingestion/preprocessor.py` | 文本去噪、正则过滤、保留有观点密度的内容 |
| `engines/consensus_engine.py` | 调用 LLM 提取市场共识、情绪评分、隐含增长率 |
| `engines/thesis_projector.py` | 调用 LLM 基于用户宏观信念评估合理增长率 |
| `engines/gap_calculator.py` | 本地计算 Gap 值，生成 OPPORTUNITY/OVERHEATED/WAIT 信号 |
| `llm/deepseek_client.py` | 封装 DeepSeek API 调用、重试机制、JSON 解析 |
| `llm/prompts.py` | 管理 Consensus Engine 和 Thesis Projector 的 Prompt 模板 |
| `persistence/` | 将审计结果写入 CSV 或 SQLite，支持追加模式 |
| `utils/logger.py` | 统一日志格式，记录运行统计信息 |

## 3. 关键类和接口定义汇总

### 3.1 配置模块 (`config/`)

```python
# config/models.py
@dataclass
class LLMConfig:
    provider: Literal["deepseek"]
    api_key: str
    model: str
    temperature: float  # 必须为 0
    max_tokens: int

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
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        base_url: str = "https://api.deepseek.com",
    ): ...

    def chat(self, system_prompt: str, user_prompt: str, temperature: float | None = None) -> LLMResponse: ...

    def chat_with_json_output(
        self,
        system_prompt: str,
        user_prompt: str,
        result_class: Type[T],
        max_retries: int | None = None,
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
    status: Literal["ok", "data_error", "llm_error"]

class GapCalculator:
    def __init__(self, thresholds: GapThresholdConfig | None = None): ...
    def calculate_gap(self, our_growth: float, implied_growth: float) -> float: ...
    def determine_signal(self, gap: float, sentiment_score: int) -> AuditSignal: ...
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

### 3.5 持久化模块 (`persistence/`)

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

# persistence/sqlite_store.py (预留)
class SQLiteReportStore(AuditReportStore):
    def __init__(self, db_path: str | Path = "audit_data.db"): ...
    # 预留接口，空实现
```

### 3.6 主程序 (`main.py`)

```python
class AliceTestPipeline:
    def __init__(self, config: AppConfig): ...
    def run(self) -> list[AuditResult]: ...
    def _process_single_target(self, target: TargetConfig) -> AuditResult: ...
    def _ingest_data(self, target: TargetConfig) -> TickerRawData: ...

def main() -> None:
    """命令行入口: python -m src.main --config config.yaml"""
    ...
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
│           AuditResult                                       │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
         ┌─────────────────┐
         │ AuditReportStore│ ──▶ audit_report.csv / SQLite
         └─────────────────┘
```

## 5. 信号判定逻辑

```python
# PRD 5.5 节定义的判定规则
if gap > 10 and sentiment_score < 40:
    signal = "OPPORTUNITY"   # 市场悲观但我们看好
elif sentiment_score > 80:
    signal = "OVERHEATED"    # 市场过热
else:
    signal = "WAIT"          # 观望
```

## 6. 后续实现优先级建议

1. **MVP 阶段**
   - `config/` 模块完整实现
   - `llm/deepseek_client.py` 完整实现
   - `engines/` 三个引擎完整实现
   - `persistence/csv_writer.py` 完整实现
   - `main.py` 基本流程

2. **数据源阶段**
   - `data_ingestion/quotes/tushare_client.py`
   - `data_ingestion/quotes/yfinance_client.py`
   - 简单的文本爬虫实现

3. **增强阶段**
   - `persistence/sqlite_store.py` 完整实现
   - 文本预处理增强
   - 调度功能集成
