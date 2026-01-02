# 港美股文本数据模块

## 概述

本模块实现港美股市场的文本数据获取，基于 Web Search + LLM 的技术方案。

## 架构

```
hk_us/
├── __init__.py          # 模块导出
├── serper_client.py     # Serper.dev 搜索客户端
├── web_fetcher.py       # 网页内容抓取器
├── agent_browser.py     # LLM 驱动的多层浏览器
├── hk_us_provider.py    # 顶层封装 (TextProvider 实现)
└── README.md            # 本文件
```

## 使用方法

### 基础用法

```python
from src.data_ingestion.text.hk_us import HKUSTextProvider

provider = HKUSTextProvider()
texts = provider.fetch_texts(
    ticker="AAPL",
    name="Apple",
    max_items=10,
)

for item in texts:
    print(f"[{item.type}] {item.title}")
    print(f"  {item.summary[:100]}...")
```

### 通过工厂类使用

```python
from src.data_ingestion.text import TextProviderFactory

# 自动根据 ticker 选择 Provider
texts = TextProviderFactory.fetch_texts("0700.HK", "腾讯控股")
```

## 配置

在 `config.yaml` 中配置：

```yaml
data_sources:
  text:
    hk_us:
      search_provider: "serper"
      browsing:
        enabled: true
        max_depth: 2
      trusted_domains:
        - "seekingalpha.com"
        - "bloomberg.com"
```

## 环境变量

| 变量名 | 说明 |
|--------|------|
| `SERPER_API_KEY` | Serper.dev API 密钥 |

## 依赖

- httpx
- beautifulsoup4
- lxml (可选)

## 测试

```bash
pytest tests/test_hk_us_provider.py -v
```
