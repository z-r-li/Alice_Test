# Alice Test 项目需求文档 (PRD)

## 市场隐含预期与认知偏差自动审计系统

---

## 1. 项目概述

| 项目 | 说明 |
|------|------|
| **项目代号** | Alice Test |
| **核心目标** | 构建自动化 Python 数据流水线，监控特定投资标的，计算**认知差 (Cognitive Gap)** —— 即"市场当前共识"与"预设宏观信念"之间的偏差 |
| **核心价值** | 不预测股价，而是系统性识别市场定价偏差带来的机会 |
| **主力模型** | DeepSeek-V4-Flash（关键路径显式指定，temperature=0） |

---

## 2. 技术栈

```yaml
编程语言:      Python 3.10+
LLM 服务商:    DeepSeek-V4-Flash
数据源:
  - A股行情:   AkShare (默认) / Tushare
  - 港美股行情: yfinance
  - A股文本:   AkShare API (研报、互动易、评级、新闻)
  - 港美股文本: Serper.dev 搜索 + LLM 多层浏览
HTTP 客户端:   httpx (异步)
网页解析:      BeautifulSoup4 + lxml
持久化存储:    SQLite 或 CSV（轻量级，方便回测）
调度频率:      每日收盘后运行
```

---

## 3. 核心流水线架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         每日流水线流程                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   步骤 1     │    │   步骤 2     │    │   步骤 3     │          │
│  │   数据摄入   │───▶│  共识引擎    │───▶│  信念投影    │          │
│  │             │    │  (模块 A)    │    │  (模块 B)    │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                   │                   │                   │
│         ▼                   ▼                   ▼                   │
│  ┌──────────────────────────────────────────────────────┐          │
│  │                      步骤 4                          │          │
│  │               认知差计算 & 信号生成                   │          │
│  └──────────────────────────────────────────────────────┘          │
│                              │                                      │
│                              ▼                                      │
│                    [ audit_report.csv ]                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 模块详细规格

### 4.1 步骤一：数据摄入 (Data Ingestion)

**目标：** 为每个标的采集量化指标和定性信号。

#### 4.1.1 硬数据（量化指标）

| 字段 | 说明 |
|------|------|
| `close_price` | 最新收盘价 |
| `pe_ttm` | 市盈率（TTM） |
| `pb` | 市净率 |
| `turnover_rate` | 换手率 |

#### 4.1.2 软数据（定性信息）

| 参数 | 规格 |
|------|------|
| **时间窗口** | 过去 48 小时 |
| **数据来源** | 券商研报摘要、主流新闻标题、机构评级、互动问答 |
| **数量限制** | 每个标的取 Top 5-10 条最有价值的文本 |
| **过滤规则** | 剔除：融资融券公告、大宗交易通知等无观点内容 |

#### 4.1.3 A股文本数据源（AkShare API）

A股文本数据通过 AkShare 提供的多个 API 获取：

| 数据类型 | API 接口 | 说明 |
|----------|----------|------|
| 研报 | `stock_research_report_em` | 东方财富研报，含标题和 PDF |
| 互动易 | `stock_sns_sseinfo` / `stock_irm_cninfo` | 投资者问答，直接反映市场担忧 |
| 评级 | `stock_institute_recommend_detail` | 机构评级变动，预期变化信号 |
| 新闻 | `stock_news_em` | 补充市场叙事 |

**配额权重分配：**

```yaml
quota_weights:
  research: 4   # 研报权重最高，最有分析价值
  irm: 3        # 互动易直接反映投资者担忧
  rating: 2     # 评级变动是预期变化信号
  news: 3       # 新闻补充市场叙事
```

#### 4.1.4 港美股文本数据源（多层浏览）

港美股无统一 API，采用 **Web Search + LLM 多层浏览** 方案：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    港美股文本获取架构                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │ SerperClient │───▶│ PageFetcher  │───▶│LLMLinkSelector│         │
│  │              │    │              │    │              │          │
│  │ Serper.dev   │    │ httpx +      │    │ DeepSeek     │          │
│  │ 搜索 API     │    │ BeautifulSoup│    │ 链接判断     │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                   │                   │                   │
│         ▼                   ▼                   ▼                   │
│    搜索结果          页面内容抓取          智能链接选择              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**数据流：**
1. **Serper 搜索**：生成查询（如 "AAPL analyst report"），获取搜索结果
2. **第一层抓取**：httpx 获取搜索结果页面内容 + 提取页面内链接
3. **LLM 链接选择**：DeepSeek 判断哪些链接值得深入
4. **第二层抓取**：获取 LLM 选中的链接（通常是具体分析文章）
5. **内容提取**：LLM 从页面提取关键投资信息

**可信域名白名单：**

| 域名 | 类型 | 说明 |
|------|------|------|
| seekingalpha.com | 研报/分析 | 深度分析文章 |
| tipranks.com | 评级汇总 | 机构评级、目标价聚合 |
| morningstar.com | 研报 | 基金评级、股票分析 |
| finance.yahoo.com | 综合 | 新闻、财报、分析师预测 |
| bloomberg.com | 新闻/分析 | 高质量权威财经 |
| reuters.com | 新闻 | 权威财经新闻 |

**成本估算（单标的）：**

| 组件 | 服务 | 成本 |
|------|------|------|
| 搜索 | Serper.dev | ~$0.003 (3次查询) |
| 页面抓取 | httpx | 免费 |
| LLM 链接选择 | DeepSeek | ~$0.0025 |
| LLM 内容提取 | DeepSeek | ~$0.02 |
| **总计** | | **~$0.025/标的** |

---

### 4.2 步骤二：共识引擎 (Module A: Consensus Engine)

**目标：** 提取市场情绪和隐含增长预期。

#### 4.2.1 LLM 配置

```yaml
model: deepseek-v4-flash
temperature: 0  # 关键：必须为 0，确保评分一致性
```

#### 4.2.2 System Prompt 模板

```markdown
# 角色
你是一位客观的市场情绪审计师。

# 任务
分析以下关于 [标的名称] 的信息：

## 输入数据
- 当前股价：[PRICE]
- PE（TTM）：[PE]
- 新闻与研报：[TEXT_DATA]

## 分析要求

### 1. 叙事提取
- 市场现在最担忧什么？
- 市场现在最期待什么？

### 2. 情绪打分
使用以下严格标准对市场整体情绪打分：

| 分数区间 | 判定标准 |
|----------|----------|
| 0-20 | 提及崩盘、危机、不可持续 |
| 21-40 | 关注成本风险、汇率风险、增长不及预期 |
| 41-60 | 多空平衡，认为已 Price-in |
| 61-80 | 强调增长逻辑，忽视风险 |
| 81-100 | 使用"无限空间"、"新纪元"等词汇 |

### 3. 隐含增长率反推
基于当前估值和情绪，市场隐含认为未来 3 年的年化增长率 (g) 大概是多少？
（保守估计）

# 输出格式
仅返回有效 JSON：
{
  "sentiment_score": <0-100 整数>,
  "sentiment_label": "<恐慌|悲观|中性|乐观|狂热>",
  "implied_growth_rate": <百分比浮点数>,
  "key_worry": "<字符串>",
  "key_hope": "<字符串>",
  "key_narrative": "<一句话总结>"
}
```

---

### 4.3 步骤三：信念投影 (Module B: Thesis Projector)

**目标：** 基于用户宏观信念评估增长潜力。

#### 4.3.1 System Prompt 模板

```markdown
# 角色
你是一位基于第一性原理的投资审计师。

# 背景信息
用户宏观信念：[USER_THESIS]
目标标的：[TICKER_NAME]

# 任务
忽略短期市场噪音。在 [USER_THESIS] 逻辑框架下，评估该标的的真实增长潜力。

请考虑：
- 结构性顺风/逆风因素
- 竞争格局定位
- 资本配置效率
- 长期需求驱动力

# 输出格式
仅返回有效 JSON：
{
  "thesis_aligned": <布尔值>,
  "our_growth": <百分比浮点数>,
  "confidence": "<高|中|低>",
  "reasoning": "<2-3 句解释>"
}
```

---

### 4.4 步骤四：认知差计算与信号生成

**目标：** 计算认知差并生成可操作信号。

#### 4.4.1 核心公式

```python
gap = our_growth - implied_growth_rate
```

#### 4.4.2 信号逻辑

```python
def generate_signal(gap: float, sentiment: int) -> str:
    if gap > 10 and sentiment < 40:
        return "OPPORTUNITY"  # 机会
    elif sentiment > 80:
        return "OVERHEATED"   # 过热
    else:
        return "WAIT"         # 观望
```

---

## 5. 配置文件规范

### 5.1 config.yaml 结构

```yaml
# LLM 配置
llm_api:
  provider: "deepseek"
  api_key: ""  # 运行期只从环境变量 DEEPSEEK_API_KEY 读取
  model: "deepseek-v4-flash"
  temperature: 0  # 必须为 0，保证评分稳定
  max_tokens: 4096
  max_retries: 2
  # Module B 思考模式配置（可选）
  thesis_thinking_enabled: false
  thesis_thinking_max_tokens: 16384

# 数据源配置
data_sources:
  # A 股行情数据源
  a_shares:
    provider: "akshare"  # 或 "tushare"
    token: ""  # 使用 Tushare 时运行期只从环境变量 TUSHARE_TOKEN 读取

  # 港美股行情数据源
  hk_us:
    provider: "yfinance"

  # 文本数据源配置
  text:
    # A 股文本源（基于 AkShare API）
    a_share:
      enabled_sources:
        - research
        - irm
        - rating
        - news
      quota_weights:
        research: 4
        irm: 3
        rating: 2
        news: 3

    # 港美股文本源（基于 Web Search）
    hk_us:
      search_provider: "serper"  # serper | serpapi
      search_api_key: ""  # 运行期只从 SERPER_API_KEY 读取
      browsing:
        enabled: true
        max_depth: 2
        max_links_per_page: 3
        link_selection_mode: "llm"  # llm | rule
      trusted_domains:
        - "seekingalpha.com"
        - "tipranks.com"
        - "morningstar.com"
        - "finance.yahoo.com"
        - "bloomberg.com"
        - "reuters.com"
      search_templates:
        research: "{ticker} {name} analyst report research"
        news: "{ticker} {name} news"
        earnings: "{ticker} earnings analysis"

  # 爬虫通用配置
  crawler:
    use_mock: false
    lookback_hours: 48
    max_items_per_ticker: 10

# 投资标的列表
targets:
  - ticker: "601985.SH"
    name: "中国核电"
    thesis: >
      AI算力需要稳定基荷电力，核电是物理刚需，
      具备类公用事业的确定性和科技股的成长性。

  - ticker: "600150.SH"
    name: "中国船舶"
    thesis: >
      全球供应链重构导致造船长周期开启，
      战略资产应按重置成本定价，而非简单的制造业PE。

  - ticker: "0700.HK"
    name: "腾讯控股"
    thesis: >
      国内社交和游戏基本盘稳固，海外游戏和云业务是增量，
      回购和分红提升股东回报，估值修复空间大。

# 输出配置
output:
  format: "csv"  # 或 "sqlite"
  path: "./output/audit_report.csv"

# 调度配置
scheduler:
  cron: "0 18 * * MON-FRI"  # 每个交易日 18:00 运行
  enabled: true

# Gap 判定阈值配置
gap_thresholds:
  opportunity_gap_min: 10.0
  opportunity_sentiment_max: 40
  overheated_sentiment_min: 80
```

### 5.2 环境变量

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `DEEPSEEK_API_KEY` | 是 | LLM 服务密钥 |
| `SERPER_API_KEY` | 否 | 港美股文本搜索 (免费 2,500次/月) |
| `TUSHARE_TOKEN` | 否 | A股数据备选方案 |

---

## 6. 输出规范

### 6.1 audit_report.csv 字段定义

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `date` | DATE | 审计日期 (YYYY-MM-DD) |
| `ticker` | STRING | 股票代码 |
| `name` | STRING | 公司名称 |
| `price` | FLOAT | 收盘价 |
| `pe_ttm` | FLOAT | 市盈率（TTM） |
| `sentiment_score` | INT | 情绪分数 (0-100) |
| `sentiment_label` | STRING | 情绪标签 |
| `implied_growth` | FLOAT | 市场隐含增长率 % |
| `our_growth` | FLOAT | 信念预期增长率 % |
| `gap` | FLOAT | 认知差 (our - implied) |
| `signal` | STRING | OPPORTUNITY / OVERHEATED / WAIT |
| `key_narrative` | STRING | 一句话市场总结 |
| `key_worry` | STRING | 主要担忧 |
| `key_hope` | STRING | 主要期待 |
| `status` | STRING | ok / data_error / llm_error / data_partial / pipeline_error / unknown |
| `needs_due_diligence` | BOOL | 是否需人工尽调；旧 CSV 缺列为未知 |
| `suggested_weight` | FLOAT | S6 建议仓位 |
| `correlation_flags` | JSON ARRAY | 同簇 / 高相关 ticker 列表 |
| `structural_exit` | JSON ARRAY | 结构性退出条件 |
| `quant_exit_target` | FLOAT | 量化退出目标（未定则为空） |
| `risk_adjusted_action` | STRING | BUY / TRIM / WAIT / EXIT |
| `risk_contribution` | FLOAT | 组合风险贡献 |

### 6.2 输出示例

```csv
date,ticker,name,price,pe_ttm,sentiment_score,sentiment_label,implied_growth,our_growth,gap,signal,key_narrative,key_worry,key_hope,status,needs_due_diligence,suggested_weight,correlation_flags,structural_exit,quant_exit_target,risk_adjusted_action,risk_contribution
2025-10-24,600150.SH,中国船舶,35.5,18.2,35,悲观,5.0,15.0,10.0,OPPORTUNITY,市场担忧钢价上涨侵蚀利润,钢材成本压力,新船订单增长,ok,false,0.05,"[]","[]",,BUY,
2025-10-24,601985.SH,中国核电,12.8,22.5,62,乐观,8.0,12.0,4.0,WAIT,AI电力需求叙事持续发酵,核准进度不确定性,电力需求持续增长,ok,false,0.0,"[]","[]",,WAIT,
```

---

## 7. 成本与风控

### 7.1 Token 优化

```python
# 仅提取研报中的有价值段落
EXTRACT_PATTERNS = [
    r"摘要[：:](.*?)(?=\n\n|\Z)",
    r"投资要点[：:](.*?)(?=\n\n|\Z)",
    r"风险提示[：:](.*?)(?=\n\n|\Z)",
    r"结论[：:](.*?)(?=\n\n|\Z)",
]
```

### 7.2 防幻觉措施

```python
def parse_llm_response(response: str, retries: int = 1) -> dict:
    """强制 JSON 输出，解析失败则重试"""
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        if retries > 0:
            # 带有明确 JSON 指令的重试
            return retry_with_json_prompt(retries - 1)
        else:
            return {"error": "JSON 解析失败", "raw": response}
```

### 7.3 预算约束

| 指标 | 目标值 |
|------|--------|
| 单标的单次运行成本 | < $0.005 |
| 每日总成本（10 个标的） | < $0.05 |
| 每标的 LLM 调用次数 | 2 次（模块 A + 模块 B） |

---

## 8. 开发优先级

### 第一阶段：核心流水线 (MVP) ✅

1. ✅ 配置文件解析器
2. ✅ 数据摄入模块（硬数据：A股/港美股行情）
3. ✅ 模块 A：共识引擎（关键路径）
4. ✅ 模块 B：信念投影（含思考模式支持）
5. ✅ 认知差计算与信号生成
6. ✅ CSV 输出

### 第二阶段：数据增强 ✅

1. ✅ A股文本数据源（AkShare API：研报、互动易、评级、新闻）
2. ✅ 港美股文本数据源（Serper + LLM 多层浏览）
3. ✅ 可信域名白名单机制
4. ✅ 付费墙检测与过滤

### 第三阶段：监控与告警

1. ⬜ 每日定时调度 (cron)
2. ⬜ 信号告警（邮件/Webhook）
3. ⬜ 历史趋势可视化
4. ⬜ SEC/HKEX 公告集成
5. ⬜ 财报电话会议记录解析

---

## 9. 开发者备注

> **关键成功因素：**
> 
> 核心难点不在代码，而在 **Prompt 调试**。
> 
> 重点任务是稳定步骤二的情绪打分 —— 避免相同输入下评分大幅波动
> （例如今天 30 分，明天 80 分）。
> 
> 核心控制手段：
> - `Temperature = 0` 是底线，不可妥协
> - Prompt 中写死评分量表
> - 强制结构化 JSON 输出

> **Token 预算：**
> 
> 我们不受 Token 限制。可放心使用 LLM 实现：
> - 搜索源列表生成
> - 爬虫程序操作
> - Agent 浏览功能
> 
> 以上均应在 `config.yaml` 中可配置。

---

## 附录 A：情绪评分量表（硬编码）

| 分数 | 标签 | 语言特征 |
|------|------|----------|
| 0-20 | 恐慌 | 崩盘、危机、不可持续、爆雷、暴跌 |
| 21-40 | 悲观 | 成本压力、汇率风险、增长不及预期、下调 |
| 41-60 | 中性 | Price-in、多空平衡、等待、观望 |
| 61-80 | 乐观 | 增长逻辑、超预期、景气度、上调目标价 |
| 81-100 | 狂热 | 无限空间、新纪元、颠覆、历史性机遇 |

---

*文档版本：2.0*
*最后更新：2026年1月*
