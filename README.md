# Alice Test

**市场隐含预期与认知偏差自动审计系统**

Alice Test 是一个自动化 Python 数据流水线，用于监控特定投资标的，计算**认知差 (Cognitive Gap)**——即"市场当前共识"与"预设宏观信念"之间的偏差。

> 🎯 **核心价值**: 不预测股价，而是系统性识别市场定价偏差带来的机会

---

## 📋 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [用户指南](#用户指南)
  - [安装依赖](#1-安装依赖)
  - [配置文件设置](#2-配置文件设置)
  - [运行程序](#3-运行程序)
  - [输出结果解读](#4-输出结果解读)
- [配置详解](#配置详解)
- [常见问题](#常见问题)

---

## 功能特性

- 🔄 自动采集 A股/港股/美股行情数据
- 📰 整合研报摘要与新闻标题
- 🌐 港美股: Serper.dev + LLM 多层浏览
- 🤖 基于 DeepSeek-V4-Flash 的市场情绪分析
- 📊 认知差计算与信号生成 (OPPORTUNITY / OVERHEATED / WAIT)
- 📁 CSV 格式审计报告输出

---

## 快速开始

```bash
# 克隆项目
git clone https://github.com/llaoleDY/Alice_Test.git
cd alice_test

# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥
export DEEPSEEK_API_KEY="your-api-key"
export TUSHARE_TOKEN="your-tushare-token"  # 可选，用于 A 股数据
export SERPER_API_KEY="your-serper-key"    # 可选，用于港美股文本

# 运行
python src/main.py --config config.yaml
```

---

## 用户指南

### 1. 安装依赖

确保你的 Python 版本为 3.10 或更高版本。

```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

**主要依赖说明：**
| 依赖 | 用途 |
|------|------|
| `openai` | DeepSeek API 调用（兼容 OpenAI SDK） |
| `tushare` | A股行情数据（可选） |
| `akshare` | A股数据备选方案 |
| `yfinance` | 港股/美股行情数据 |
| `httpx` | 港美股文本异步 HTTP 请求 |
| `beautifulsoup4` | 港美股网页内容解析 |
| `pyyaml` | 配置文件解析 |
| `pydantic` | 数据模型校验 |

### 2. 配置文件设置

在项目根目录创建 `config.yaml` 文件：

```yaml
# LLM 配置
llm_api:
  provider: "deepseek"
  model: "deepseek-v4-flash"      # 非 thinking 打分/汇总路径（Module A/S3/S7）
  model_pro: "deepseek-v4-pro"    # thinking 深推理路径（S1/S2/S4/S5/B）
  api_key: ""  # 运行期从环境变量 DEEPSEEK_API_KEY 读取（或写 ${YOUR_ENV} 占位，见下）
  temperature: 0  # 非 thinking 路径必须为 0（非 0 直接报错）；thinking 路径此参数为 no-op
  max_tokens: 4096
  reasoning_effort: "high"        # thinking 路径推理强度：high（默认）| max（仅最难阶段）

# 数据源配置
data_sources:
  a_shares:
    provider: "akshare"  # 可选: "tushare" 或 "akshare"
    token: ""  # 使用 tushare 时从环境变量 TUSHARE_TOKEN 读取（或写 ${YOUR_ENV} 占位）
  hk_us:
    provider: "yfinance"
  # 文本数据源配置
  text:
    hk_us:
      search_provider: "serper"
      search_api_key: ""  # 运行期从 SERPER_API_KEY 读取
      browsing:
        enabled: true
        max_depth: 2
        max_links_per_page: 3
        link_selection_mode: "llm"
      trusted_domains:
        - "seekingalpha.com"
        - "finance.yahoo.com"
        - "reuters.com"
      search_templates:
        research: "{ticker} {name} analyst report research"
        news: "{ticker} {name} news"

# 监控标的配置
targets:
  - ticker: "601985.SH"
    name: "中国核电"
    thesis: |
      AI算力发展将大幅增加电力需求，核电作为稳定基荷电源将充分受益。
      公司在建机组规模行业领先，2025-2027年将迎来机组集中投产期。
      预期未来3年净利润复合增长率约12%。
    
  - ticker: "AAPL"
    name: "苹果公司"
    thesis: |
      iPhone 换机周期叠加 AI 功能升级，预计带来新一轮增长。
      服务业务持续高毛利贡献，生态护城河稳固。

# Gap 阈值配置
gap_thresholds:
  opportunity_gap_min: 10.0
  opportunity_sentiment_max: 40
  overheated_sentiment_min: 80

# 输出配置
output:
  format: "csv"
  path: "audit_report.csv"
```

### 3. 运行程序

**基础用法：**

```bash
# 使用默认配置运行
python src/main.py

# 指定配置文件
python src/main.py --config path/to/config.yaml

# 指定输出文件
python src/main.py --output my_report.csv

# 只处理特定标的
python src/main.py --ticker 601985.SH

# 详细输出模式（调试用）
python src/main.py --verbose
```

**命令行参数说明：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config` | 配置文件路径 | `config.yaml` |
| `--output` | 输出报告路径 | `audit_report.csv` |
| `--ticker` | 只处理指定标的 | 处理所有标的 |
| `--verbose, -v` | 详细输出模式 | 关闭 |

**定时运行（Linux cron 示例）：**

```bash
# 每日收盘后 17:00 运行
0 17 * * 1-5 cd /path/to/alice_test && python src/main.py >> logs/cron.log 2>&1
```

### 4. 输出结果解读

运行完成后，会生成 `audit_report.csv` 文件：

| 字段 | 说明 |
|------|------|
| `date` | 审计日期 |
| `ticker` | 股票代码 |
| `name` | 公司名称 |
| `price` | 收盘价 |
| `pe_ttm` | 市盈率（TTM） |
| `sentiment_score` | 情绪分数 (0-100) |
| `sentiment_label` | 情绪标签（恐慌/悲观/中性/乐观/狂热） |
| `implied_growth` | 市场隐含增长率 % |
| `our_growth` | 你的预期增长率 % |
| `gap` | 认知差 (our - implied) |
| `signal` | **交易信号** |
| `key_narrative` | 一句话市场总结 |
| `key_worry` | 主要担忧 |
| `key_hope` | 主要期待 |

**信号解读：**

| 信号 | 条件 | 含义 |
|------|------|------|
| `OPPORTUNITY` | gap ≥ 5% | 市场低估，可能存在买入机会 |
| `OVERHEATED` | gap ≤ -5% | 市场高估，需谨慎 |
| `WAIT` | -5% < gap < 5% | 定价合理，继续观察 |

---

## 配置详解

### 标的代码格式

| 市场 | 格式 | 示例 |
|------|------|------|
| A股（上海） | `XXXXXX.SH` | `601985.SH` |
| A股（深圳） | `XXXXXX.SZ` | `000001.SZ` |
| 港股 | `XXXXX.HK` | `00700.HK` |
| 美股 | 无后缀 | `AAPL`, `TSLA` |

### 环境变量

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | 是 | LLM 服务密钥 |
| `SERPER_API_KEY` | 否 | 港美股文本搜索 (2,500次/月免费) |
| `TUSHARE_TOKEN` | 否 | A股数据备选方案 |

### 密钥来源与 `${ENV}` 占位

密钥**绝不驻留配置对象**：`api_key` / `token` 等密钥字段在加载和导出（`dump` / `repr` / 日志）中永远不出现明文，运行期由各 getter 即时读取。两种写法：

1. **留空**（推荐）：字段写 `""`，运行期从固定环境变量（`DEEPSEEK_API_KEY` / `TUSHARE_TOKEN`）读取。
2. **`${ENV}` 占位**：字段写成 `api_key: "${MY_KEY}"`，运行期 getter 即时从环境变量 `MY_KEY` 解析。占位只是**引用**、不是明文；解析值不写回配置对象。

`${ENV}` 占位规则：
- **非密钥字段**（如路径）在加载时即解析 `${VAR}`，支持一值多次出现、与文本混排（如 `${HOME}/data`）。
- **被引用的环境变量缺失**会直接报错（fail-closed，指明缺失的变量名），绝不静默置空。
- 仅支持 `${VAR}` 一种语法（不支持 `${VAR:-default}` / `$` 转义）。

### 思考模式（高级）

模型 / thinking / effort 按阶段分流（参 PRD 4.2 / 迁移计划 §4 **目标矩阵**）：非 thinking 打分与汇总路径（Module A / S3 / S7）用 `model`（v4-flash）+ `temperature=0`，保证评分逐位可复现；thinking 深推理路径（目标 S1/S2/S4/S5、Module B/S5）用 `model_pro`（v4-pro）+ `reasoning_effort`。thinking 下 `temperature` 为 no-op，复现性改由硬编码量表 + JSON schema 保证。

> **现状**：thinking 当前仅 **Module B / S5** 经 `thesis_thinking_enabled` 接线，`reasoning_effort` 为客户端级默认（`high`）；S1–S4 的 per-stage thinking 与 S4 的 `effort=max` 待团队拍板后接线。

Module B / S5（信念投影与综合）可启用 DeepSeek 思考模式，在输出前进行深度推理：

```yaml
llm_api:
  # ... 其他配置 ...
  model_pro: "deepseek-v4-pro"   # thinking 路径模型
  reasoning_effort: "high"        # high（默认）| max（仅最难阶段，成本最高）
  thesis_thinking_enabled: true   # 为 Module B / S5 启用思考模式
  thesis_thinking_max_tokens: 16384
```

| 模式 | 优点 | 缺点 |
|------|------|------|
| 标准模式 | 响应快、成本低 | 复杂推理能力一般 |
| 思考模式 | 推理更深入准确 | Token 消耗增加 2-3 倍 |

**建议：** 初期使用标准模式，如发现 Module B 输出质量不佳再启用思考模式。

---

## 常见问题

### Q: 运行时提示 "配置文件不存在"

确保 `config.yaml` 文件在当前工作目录下，或使用 `--config` 参数指定完整路径。

### Q: API 调用失败

1. 检查 `DEEPSEEK_API_KEY` 环境变量是否设置正确
2. 确认网络可以访问 DeepSeek API
3. 使用 `--verbose` 参数查看详细错误信息

### Q: A股数据获取失败

- 使用 Tushare 时，确保已设置 `TUSHARE_TOKEN` 且有足够积分
- 尝试切换到 AkShare：在配置文件中设置 `data_sources.a_shares.provider: "akshare"`

### Q: 如何添加新的监控标的？

在 `config.yaml` 的 `targets` 列表中添加新条目：

```yaml
targets:
  - ticker: "NEW_TICKER"
    name: "公司名称"
    thesis: |
      你对这个公司的投资逻辑...
```

---

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 编程语言 | Python 3.x |
| LLM 服务 | DeepSeek-V4-Flash |
| A股数据 | Tushare / AkShare |
| 港美股数据 | yfinance |
| 存储 | CSV |

---

## License

MIT License
