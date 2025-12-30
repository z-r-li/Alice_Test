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
- 🤖 基于 DeepSeek-V3 的市场情绪分析
- 📊 认知差计算与信号生成 (OPPORTUNITY / OVERHEATED / WAIT)
- 📁 CSV 格式审计报告输出

---

## 快速开始

```bash
# 克隆项目
git clone <repository-url>
cd alice_test

# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥
export DEEPSEEK_API_KEY="your-api-key"
export TUSHARE_TOKEN="your-tushare-token"  # 可选，用于 A 股数据

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
| `pyyaml` | 配置文件解析 |
| `pydantic` | 数据模型校验 |

### 2. 配置文件设置

在项目根目录创建 `config.yaml` 文件：

```yaml
# LLM 配置
llm_api:
  provider: "deepseek"
  model: "deepseek-chat"
  api_key: "${DEEPSEEK_API_KEY}"  # 支持环境变量
  temperature: 0  # 重要：保持为 0 以确保评分一致性
  max_tokens: 2000

# 数据源配置
data_sources:
  a_shares:
    provider: "akshare"  # 可选: "tushare" 或 "akshare"
    token: "${TUSHARE_TOKEN}"  # 使用 tushare 时需要
  hk_us:
    provider: "yfinance"

# 监控标的配置
targets:
  - ticker: "601985.SH"
    name: "中国核电"
    thesis: |
      AI算力发展将大幅增加电力需求，核电作为稳定基荷电源将充分受益。
      公司在建机组规模行业领先，2025-2027年将迎来机组集中投产期。
      预期未来3年净利润复合增长率约12%。
    expected_growth: 12.0
    
  - ticker: "AAPL"
    name: "苹果公司"
    thesis: |
      iPhone 换机周期叠加 AI 功能升级，预计带来新一轮增长。
      服务业务持续高毛利贡献，生态护城河稳固。
    expected_growth: 8.0

# Gap 阈值配置
gap_thresholds:
  opportunity: 5.0   # gap >= 5% 触发 OPPORTUNITY 信号
  overheated: -5.0   # gap <= -5% 触发 OVERHEATED 信号

# 输出配置
output:
  format: "csv"
  path: "audit_report.csv"
  append: true  # 追加模式
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

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | ✅ |
| `TUSHARE_TOKEN` | Tushare API Token | 使用 Tushare 时需要 |

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
    expected_growth: 10.0  # 你预期的增长率
```

---

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 编程语言 | Python 3.x |
| LLM 服务 | DeepSeek-V3 (主力) / GPT-4o-mini (备选) |
| A股数据 | Tushare / AkShare |
| 港美股数据 | yfinance |
| 存储 | SQLite / CSV |

---

## License

MIT License
