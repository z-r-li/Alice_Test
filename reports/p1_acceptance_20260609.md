# P1 验收报告 — 真实标的端到端运行（2026-06-09）

验收方式：真实 DeepSeek（`deepseek-chat`，实际由 **deepseek-v4-flash** 服务）+ 真实行情/财报/文本，
3 个标的（601985.SH、600150.SH、0700.HK）各自独立进程跑 `src/main.py --ticker X --verbose`，
token/成本由 SDK 层打点（不改 repo 代码）精确计量。里程碑测试
`pytest tests/integration/test_e2e_601985.py -m integration` 通过。

## 一、结论（TL;DR）

- **机械链路达标**：3 标的全部端到端真实跑通，S1–S5 五阶段产物齐全、可审查，全程未回退单次投影，
  16 次结构化 LLM 调用 **0 次 JSON 解析失败、0 次重试**；CSV 保持 14 列向后兼容。
- **证据链质量未达标**：S1（命题/kill-criteria）与 S2（逻辑链/权重）三标的全部合格；
  **S3/S4 三标的全部不合格**——已知缺口「`build_evidence()` 忽略 condition」坐实且后果比预期重
  （详见 §四）；S5 一过两挂。证据链目前「形通而实空」：定量环节拿到的是真实但与条件无关的公司级财务。
- **成本与速度远超预期**：单标的 LLM 成本 **$0.0005–0.0006**、单次调用 ≤3.2s；瓶颈完全在数据摄入
  （A股文本爬虫），不在 LLM。头号风险（DeepSeek 是否可靠/快/便宜）**正面回答，无需退方案 B**（§六）。

## 二、每标的结果

| 标的 | 信号 | Gap | our / implied | Sentiment | S1 | S2 | S3 | S4 | S5 |
|---|---|---|---|---|---|---|---|---|---|
| 601985.SH 中国核电 | WAIT | +2.0% | 7.0 / 5.0 | 45 | ✓ | ✓ | ✗ | ✗ | ✓ |
| 600150.SH 中国船舶 | WAIT | +18.3% | 26.3 / 8.0 | 65 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 0700.HK 腾讯控股 | WAIT | −4.5% | 8.0 / 12.5 | 72 | ✓ | ✓ | ✗ | ✗ | ✗ |

**601985.SH**：命题（AI 算力→核电基荷刚需）被拆为 5 环节、权重和恰 1.0、条件全部带数值阈值。S4 财务
数字与东财/Yahoo 核对全部真实（营收 820.8 亿、PE 22.675、forward PE 标注 derived_from_history），
S5 给出 our_growth=7.0%（锚定 revenue_cagr）、confidence=低（与证据缺口一致）、reasoning 逐条可追溯
——是三标的中最健康的一条链。但 4 个定量环节拿到逐字节相同的公司级证据，与「全球 AI 用电量增速」
「装机容量」「板块溢价率」等条件完全错配；环节 5「无法判断」却未入尽调队列。

**600150.SH**：S1/S2 质量好（重置成本命题可证伪、5 环节条件全带阈值）。但 S3 把 Clarksons 订单量、
船价指数、产能利用率、Wind 行业 ROE、重置成本全部硬标 quantitative（引擎一项都算不出），S4 用同一份
真实但无关的财务证据**全部标 supports=true / confidence=高**——证据错配冒充验证，5 个条件实际 0 个
被检验；S5 照抄受并表抬高的历史 CAGR 26.3%（同份证据 revenue_yoy 仅 14.0%）并给出「市值有望达重置
成本 1.5 倍」的无证据结论。幸而 sentiment 65 触发 PRD 5.5 规则兜底（gap>10 但情绪不悲观→WAIT），
拦住了一个证据不足的看多信号。

**0700.HK**：文本路径真实（Serper 搜到 10 条资讯入共识）。S4 数字与 yfinance 核对一致（营收 7517.7 亿
CNY、毛利率 56.2%、forward PE 11.81、PEG 1.35），但暴露**新 bug**：yfinance 返回的最旧一期全空，导致
revenue_cagr/earnings_cagr=null、四个 trend 全 unknown；S5 的 our_growth=8.0 在 reasoning 中无任何推导
（证据中唯一增长数据是 revenue_yoy 13.86%），gap=−4.5% 建立在无锚数字上；「多数环节需尽调」的说法与
S4 尽调队列为空自相矛盾。

## 三、成本与时长（SDK 层实测，三标的合计 ≈ $0.0017）

| 标的 | 墙钟 | LLM 调用 | prompt tok | completion tok | 缓存命中 tok | 成本(v4-flash 现价) | 最大单次时延 | JSON 重试 | 回退 |
|---|---|---|---|---|---|---|---|---|---|
| 601985.SH | 147.2s | 6 | 3,281 | 1,100 | 1,152 | $0.000609 | 3.09s | 0 | 无 |
| 600150.SH | 165.8s | 5 | 2,705 | 903 | 512 | $0.000561 | 3.15s | 0 | 无 |
| 0700.HK | 13.4s | 5 | 2,845 | 718 | 512 | $0.000529 | 2.07s | 0 | 无 |

- 价格按官方现价计算：v4-flash 输入 $0.14/1M（缓存命中 $0.0028）、输出 $0.28/1M。repo 内
  `get_cost_estimate` 默认值是 V3 时代价格（$0.27/$1.10），高估 2–4 倍，需更新。
- **A股 147–166s 的大头不是 LLM**：上证 e 互动爬取循环 72 次约 85s（最终 0 条）+ akshare 财报逐页
  抓取 30–50s；LLM 合计仅约 15s/标的。港股全链路 13.4s。
- 运行摘要日志「0 LLM calls, 0 tokens used」是假的（`log_llm_call` 无调用方），勿采信。

## 四、本次修复（随验收提交）

1. **里程碑测试配置缺陷**：未指定 `a_shares.provider`，默认 tushare 在无 TUSHARE_TOKEN 环境直接失败
   （6/4 通过疑似依赖当时环境的 token）。已显式改为 akshare。
2. **行情降级路径从未能工作**：`QuoteData.price_close` 的 `gt=0` 约束使 main 的占位构造
   （`price_close=0.0` + data_error）必然抛 ValidationError。已放为 `ge=0` 并注明 0.0=占位语义。
3. **A股行情主源在本网络持续不可用**：东财 push2his 接口连接被远端重置（重试无效，属网络环境而非抖动）。
   新增 `FallbackQuotesProvider`：AkShare 主源 → Yahoo A 股镜像（601985.SH→601985.SS，带 PE/PB）降级，
   两 A 股实跑均由降级源提供真实行情（腾讯行情与 Yahoo 收盘价 9.07 互相印证）。
4. **财联社源从未工作**：akshare 1.18 已将 `stock_telegraph_cls` 更名 `stock_info_global_cls`
   （AttributeError）；且该端点在本网络会无限挂起（实测 >5min）。已做接口名兼容 + 30s 硬超时降级。
   （配套新增/更新 14 个离线单测；全量离线 357 passed / 2 skipped。）

## 五、问题清单（给 session 3 与后续迭代）

**P0 — 证据链中段（S3→S4→S5 condition 对齐），本次验收不合格的根因：**

1. **S3 不知道引擎能力边界**：三标的 13 个定量环节的 proxy_spec 全部指向引擎算不出的数据
   （IEA/Clarksons/Wind/分部收入/回购金额/年报披露项）。S3 prompt 须给出可计算指标白名单
   （营收/毛利净利率/OCF/PE/PEG/CAGR…），越界环节强制 due_diligence；流水线应加 proxy_spec 与引擎
   能力的代码校验。
2. **`build_evidence()` 忽略 `condition`**（参数声明未使用，financial_analysis.py）：所有定量环节
   复用同一份公司级证据；600150 还被通用启发式标成 supports=true/高置信。应按 condition 取数，
   覆盖不了的显式 `needs_due_diligence=true`。
3. **缺数据不入尽调队列**：定性路径 LLM 输出 schema 缺 `needs_due_diligence` 字段；建议规则兜底
   （data 为空且 confidence=低 → 自动入队）。三标的 due_diligence_queue 全部为空，与大量「无法判断」
   的 finding 矛盾。
4. **S5 输入缺 condition 与 weight**（缺口②坐实）：synthesis 只收 statement/supports/confidence/finding,
   无从发现证据不对题；S2 权重未参与综合。同时 S5 prompt 须强制 our_growth 给出逐步推导并引用证据字段
   （0700 的 8.0 是无锚数字；600150 照抄并表抬高的 CAGR）。

**P1 — 计算与提示质量：**

5. supports 启发式方向性错误：601985 环节4 条件「PE 持续高于 20 倍」实际满足（22.675）却判 false。
6. yfinance 财报首期全空（数据源固有）未被剔除 → 0700 的 CAGR/trend 全 unknown；引擎应跳过空期再算。
7. earnings_cagr 低基数失真（600150 的 146% → forward PE 8.5 / PEG 0.14 误导 S5）；异常 CAGR 应加警示。
8. S2 允许把命题结论（600150 环节5、0700 环节3）或 kill criterion（601985 环节5）当作带权驱动环节
   ——循环论证；prompt 应要求环节为因果驱动项、一环节一主张。
9. 文本覆盖度未进产物：A股本次仅 2 条新闻撑起 sentiment/implied_growth，S5 不知情。应记录素材覆盖度
   元数据，覆盖过薄时显式降级。
10. 遥测/产物卫生：「0 LLM calls」假统计；同一份 evidence 在产物里全量重复嵌套 5 遍；S1
    `original_thesis`/S2 `thesis_ref` 溯源字段为 null。
11. `config.example.yaml` 的 `gap_thresholds` 简化模式键（opportunity/overheated）被 pydantic 静默丢弃,
    实际生效的是 PRD 5.5 高级模式默认值（gap>10 且 sentiment<40）——示例配置误导，需对齐或实现。
12. 港美股浏览器对 >1MB 页面整页丢弃（Yahoo quote 页），应截断而非放弃。

**环境限制（非代码，影响 A 股文本面）**：本机网络对 sina（评级）、cninfo（公告）DNS 解析失败,
东财 push2his/push2 行情接口被远端重置;研报/e互动取 0 条。A 股共识基础因此偏薄——属 #65 源扩充
与部署环境选型（P2 专用机器）要解决的问题。

## 六、头号风险回答：DeepSeek 跑 S1–S5 是否可靠、是否快/便宜到 thesis 不过时？

**可靠——是。** 16 次结构化调用（temperature=0、JSON-only）全部一次解析成功，0 重试 0 失败,
无一次流水线回退；S1/S2 产物质量稳定合格，S5 在证据充分时（601985）推理可追溯、置信度自评诚实。
本次发现的所有质量问题都出在**我们的 prompt/代码逻辑**（S3 能力边界、S4 condition 对齐），
没有一个是模型能力或稳定性问题。

**快——是。** 单次调用 ≤3.2s，LLM 合计约 15s/标的；端到端 13s（港股）～166s（A股，瓶颈是爬虫不是
模型）。即使 A 股全链路 3 分钟，对「每日 cron 审计」的时效要求也绰绰有余，thesis 不会过时。

**便宜——是，且比立项时假设便宜一个数量级。** v4-flash 现价下单标的 $0.0005–0.0006,
100 标的×每日一跑 ≈ **$0.06/天（约 $1.8/月）**。成本不构成任何约束。

**结论：无需退方案 B。** 真正的风险不在 DeepSeek，而在证据链中段逻辑（§五 P0,1–4 条,
都是明确的、可修的 prompt/代码工作）和 A 股文本源可得性（#65）。
**一个硬期限**：`deepseek-chat` 别名 2026-07-24 彻底退役（当前路由 v4-flash），须在此前把默认模型名
迁移为显式 `deepseek-v4-flash` 并更新 `get_cost_estimate` 价格常量。
