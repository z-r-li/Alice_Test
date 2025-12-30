# AKShare 推荐 API 列表

本文档记录 Alice Test 项目中使用的 AKShare 接口及其实现状态。

## 文本数据接口

| 序号 | 接口名 | 类别 | 推荐度 | 实现状态 | 备注 |
|------|--------|------|--------|----------|------|
| 1 | `stock_news_em` | 新闻 | ⭐⭐⭐ | ✅ 已实现 | A 股新闻核心接口 |
| 2 | `stock_research_report_em` | 研报 | ⭐⭐⭐ | ✅ 已实现 | A 股研报核心接口 |
| 3 | `stock_irm_cninfo` | 互动易 | ⭐⭐⭐ | ✅ 已实现 | 深市投资者提问 |
| 4 | `stock_irm_ans_cninfo` | 互动易 | ⭐⭐⭐ | ✅ 已实现 | 深市公司回答 |
| 5 | `stock_sns_sseinfo` | 互动易 | ⭐⭐⭐ | ✅ 已实现 | 沪市问答合一 |
| 6 | `stock_institute_recommend` | 机构 | ⭐⭐⭐ | 🔲 可选 | 机构推荐汇总 |
| 7 | `stock_institute_recommend_detail` | 机构 | ⭐⭐⭐ | ✅ 已实现 | 评级变动记录 |

## 实现说明

### 新闻数据 (`stock_news_em`)

- **实现文件**: `src/data_ingestion/text/a_share/news_fetcher.py`
- **功能**: 获取个股相关新闻，支持时间窗口过滤

### 研报数据 (`stock_research_report_em`)

- **实现文件**: `src/data_ingestion/text/a_share/research_fetcher.py`
- **功能**: 获取机构研报，提取目标价和评级信息

### 互动易数据

#### 深市 (`stock_irm_cninfo`, `stock_irm_ans_cninfo`)

- **实现文件**: `src/data_ingestion/text/a_share/cninfo_irm_fetcher.py`
- **功能**: 获取深市互动易问答，支持问题和回答的配对

#### 沪市 (`stock_sns_sseinfo`)

- **实现文件**: `src/data_ingestion/text/a_share/sse_interactive_fetcher.py`
- **功能**: 获取沪市互动易问答

### 机构评级 (`stock_institute_recommend_detail`)

- **实现文件**: `src/data_ingestion/text/a_share/rating_change_fetcher.py`
- **功能**: 获取机构评级变动记录，生成评级变化摘要

## 数据协调器

`AShareTextCoordinator` 负责统一调度各数据源，按配额权重分配获取数量：

```python
from src.data_ingestion.text.a_share import AShareTextCoordinator

coordinator = AShareTextCoordinator()
items = coordinator.fetch_texts(
    ticker="601985.SH",
    name="中国核电",
    lookback_hours=48,
    max_items=10,
)
```
