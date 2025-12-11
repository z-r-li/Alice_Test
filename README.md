# Alice_Test

Alice Test is a Python pipeline for A-share and HK/US stocks that uses market data plus research/news with LLMs to infer a 3-year market-implied growth rate, compare it with your thesis from config, and quantify the cognitive gap to guide contrarian entries and long-term holds.

Alice Test 是一个用于 A 股与港美股的 Python 自动审计流水线，结合行情数据与研报/新闻，用大模型反推“市场隐含 3 年增长率”，再与你在 config 中写下的长期投资逻辑对比，量化“认知差”，为逆向布局与长期持有提供结构化参考。

Alice Test is an automated Python pipeline for monitoring selected equities (e.g. nuclear power, shipbuilding, internet giants) and auditing the “Cognitive Gap” between:

·Market implicit expectations inferred from price, valuation and recent narratives

·Your own macro / structural investment thesis

Alice Test 是一个面向投资者的 Python 自动化流水线，用来长期监控一篮子标的（如：核电、造船、腾讯等），重点不是“预测股价”，而是量化“认知差”：
当前市场隐含的增长预期 vs. 你基于宏观/产业逻辑得出的合理预期

Instead of predicting prices, the system estimates:

·A market-implied 3-year growth rate using LLM-summarized sentiment & valuation

·A thesis-based 3-year growth rate using your pre-defined macro view

The Gap = Our_Expected_Growth − Market_Implied_Growth, and assigns signals:

·OPPORTUNITY when market is pessimistic vs your thesis
·OVERHEATED when sentiment is euphoric
·WAIT otherwise

Daily runs generate an audit_report.csv containing price, sentiment score, both growth rates, gap, final signal and a key narrative sentence for each ticker.

系统会在每日收盘后自动完成以下工作：

1.抓数&抓话术
  
  获取最新收盘价、估值指标（PE、PB、换手率等）
  
  抓取过去 48 小时内的核心研报观点和新闻标题，过滤掉无关公告，只保留“有观点的文本”

2.市场共识引擎（Consensus Engine, CE）
  
  调用 LLM 总结市场现在在担心什么、期待什么
  
  按 0–100 对市场情绪打分（恐慌 → 狂热）
  
  在估值与情绪的约束下，反推市场隐含的 未来 3 年年化增长率
  
3.信念投影器（Thesis Projector, TP）

  读取 config.yaml 中你为每个标的写下的宏观/产业信念
  
  要求 LLM 忽略短期噪音，从第一性原理评估该标的的合理长期增长率
  
4.审计裁决（Gap Calculation, GC）
  
  本地 Python 计算：Gap = Our_Expected_Growth − Market_Implied_Growth

  按规则输出：
  
  OPPORTUNITY（机会）
  
  OVERHEATED（过热）
  
  WAIT（观望）

最终结果写入 audit_report.csv，包含日期、Ticker、价格、情绪分数、市场隐含增长、我们预期增长、    Gap、信号，以及一句总结性的关键叙事，帮助你从“价格波动”切回“逻辑对不对”。

Core Pipeline：

Data Ingestion

Pulls latest close, PE (TTM), PB, turnover etc.

Scrapes broker reports & news headlines (last 48h), filters to opinion-style texts only.

Consensus Engine (CE)

LLM module that:

Extracts current market concerns & hopes

Scores sentiment from 0–100 (panic → euphoria)

Infers the market-implied 3-year growth rate

Thesis Projector (TP)

LLM module that projects your configurable macro thesis onto each ticker

Outputs your own expected 3-year growth rate under that thesis

Gap Calculation (GC)

Pure Python logic computing the growth gap and mapping to discrete trading signals.

Tech Stack

Language: Python 3.x

LLM API: DeepSeek-V3 / deepseek-chat, GPT-4o-mini (temperature = 0 for stability)

Market Data: Tushare / AkShare (A-share), yfinance (HK/US)

Storage: SQLite or CSV (lightweight, backtest-friendly)

Config: config.yaml with tickers & per-ticker thesis text

技术与实现要点

语言：Python 3.x

大模型：deepseek-chat（temperature=0 保证评分稳定）

数据源：Tushare / AkShare（A股），yfinance（港/美股）

存储：SQLite

配置：config.yaml 中为每个 ticker 绑定一段自然语言“投资信念”

你可以将本仓库理解为一个 “市场认知 vs. 自己逻辑” 的自动对账系统：

当系统持续提醒“市场悲观、逻辑健康”时，你就知道该认真研究“逆向机会”在哪里了。

