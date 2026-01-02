# 港美股文本数据获取 - 详细设计

> Alice Test 项目港美股多层浏览架构设计文档

---

## 1. 背景与动机

### 1.1 问题

| A股 | 港美股 |
|-----|--------|
| AkShare API 直接返回研报列表 + PDF URL | 无统一 API |
| 结构化数据，一次调用获取 | 需要 Web 搜索 + 爬取 |
| 数据源可控 | 数据分散在多个网站 |

### 1.2 挑战

```
单层浏览问题：

搜索 "AAPL research report"
        │
        ▼
搜索结果：SeekingAlpha 列表页、TipRanks 汇总页...
        │
        ▼
获取这些页面 → 只是"关于研报的描述"，不是研报本身
```

**解决方案：多层浏览 + LLM 智能链接选择**

---

## 2. 架构设计

### 2.1 组件架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HkUsTextProvider                            │
│                    (TextProvider 接口实现)                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                       AgentBrowser                           │   │
│  │                    (多层浏览协调器)                           │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │                                                             │   │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │   │
│  │   │ SerperClient │  │ PageFetcher  │  │LLMLinkSelector│    │   │
│  │   │              │  │              │  │              │     │   │
│  │   │ Serper.dev   │  │ httpx +      │  │ DeepSeek     │     │   │
│  │   │ 搜索 API     │  │ BeautifulSoup│  │ 链接判断     │     │   │
│  │   └──────────────┘  └──────────────┘  └──────────────┘     │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                          完整数据流                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  输入: ticker="0700.HK", name="腾讯控股"                             │
│                          │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 1: 生成搜索查询                                         │   │
│  │ - "0700.HK analyst report"                                   │   │
│  │ - "Tencent research rating"                                  │   │
│  │ - "0700.HK earnings analysis"                                │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 2: Serper 搜索 (消耗 API 额度)                          │   │
│  │ 返回: [{title, link, snippet}, ...]                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 3: 第一层页面抓取 (httpx, 免费)                         │   │
│  │ - 获取搜索结果 URL 的完整页面内容                             │   │
│  │ - 提取正文 + 页面内链接                                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 4: LLM 链接选择 (DeepSeek, ~$0.001)                     │   │
│  │ - 输入: 页面内容 + 候选链接列表                               │   │
│  │ - 输出: 值得深入的 2-3 个链接                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 5: 第二层页面抓取 (httpx, 免费)                         │   │
│  │ - 获取 LLM 选中的链接页面                                     │   │
│  │ - 通常是具体的分析文章、研报详情                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 6: LLM 内容提取 (DeepSeek, ~$0.002)                     │   │
│  │ - 从页面正文提取关键投资信息                                  │   │
│  │ - 结构化输出: 摘要、评级、目标价等                            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  输出: list[TextItem]                                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 配置设计

### 3.1 配置结构

```yaml
data_sources:
  text:
    hk_us:
      # 搜索服务配置
      search_provider: "serper"           # serper | serpapi
      search_api_key: ""                  # 留空从 SERPER_API_KEY 读取
      
      # 多层浏览配置
      browsing:
        max_depth: 2                      # 最大深度 (1=仅搜索结果)
        max_links_per_page: 3             # 每页最多跟踪链接数
        link_selection_strategy: "llm"    # llm | heuristic
        request_delay: 1.0                # 请求间隔(秒)
        timeout: 15.0                     # 单页超时
      
      # 可信域名白名单
      trusted_domains:
        - "seekingalpha.com"
        - "tipranks.com"
        - "morningstar.com"
        - "finance.yahoo.com"
        - "reuters.com"
        - "bloomberg.com"
```

### 3.2 配置模型

```python
class BrowsingConfig(BaseModel):
    """多层浏览配置"""
    max_depth: int = 2
    max_links_per_page: int = 3
    link_selection_strategy: Literal["llm", "heuristic"] = "llm"
    request_delay: float = 1.0
    timeout: float = 15.0

class HKUSTextSourceConfig(BaseModel):
    """港美股文本源配置"""
    search_provider: Literal["serper", "serpapi"] = "serper"
    search_api_key: str = ""
    browsing: BrowsingConfig = Field(default_factory=BrowsingConfig)
    trusted_domains: list[str] = Field(default_factory=lambda: [...])
```

---

## 4. 成本分析

### 4.1 API 调用成本

| 组件 | 服务商 | 单次成本 | 免费额度 |
|------|--------|----------|----------|
| 搜索 | Serper.dev | $0.001 | 2,500次/月 |
| 页面抓取 | httpx | 免费 | 无限 |
| 链接选择 | DeepSeek | ~$0.0005 | - |
| 内容提取 | DeepSeek | ~$0.002 | - |

### 4.2 单标的单次运行成本

```
搜索查询:           3 次 × $0.001 = $0.003 (Serper)
页面抓取:           ~15 次 × $0    = $0     (httpx)
链接选择 LLM:       ~5 次 × $0.0005 = $0.0025 (DeepSeek)
内容提取 LLM:       ~10 次 × $0.002 = $0.02  (DeepSeek)
────────────────────────────────────────────
总计:               ~$0.025/标的/次
```

### 4.3 月度预算（事件驱动模式）

```
假设:
- 港美股标的: 5 个
- 每标的月度事件: 4 次（财报 + 重大新闻）

月度 Serper 调用:  5 × 4 × 3 = 60 次  << 2,500 次免费额度 ✓
月度 DeepSeek:     5 × 4 × $0.025 = $0.50/月
```

---

## 5. 可信域名说明

### 5.1 核心域名

| 域名 | 类型 | 特点 |
|------|------|------|
| seekingalpha.com | 研报/分析 | 深度分析文章，部分付费 |
| tipranks.com | 评级汇总 | 机构评级、目标价聚合 |
| morningstar.com | 研报 | 基金评级、股票分析 |
| finance.yahoo.com | 综合 | 新闻、财报、分析师预测 |
| reuters.com | 新闻 | 权威财经新闻 |
| bloomberg.com | 新闻/分析 | 高质量，部分付费墙 |

### 5.2 扩展域名（可选）

| 域名 | 类型 |
|------|------|
| fool.com | 投资分析 |
| investopedia.com | 教育/分析 |
| wsj.com | 新闻（付费墙较严） |
| ft.com | 新闻（付费墙较严） |
| barrons.com | 深度分析 |

---

## 6. 错误处理

### 6.1 搜索失败

```python
class SerperClient:
    def search(self, query: str) -> list[SearchResult]:
        try:
            response = httpx.post(...)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Serper API 限流，等待重试")
                time.sleep(60)
                return self.search(query)  # 重试一次
            raise
```

### 6.2 页面抓取失败

```python
class PageFetcher:
    def fetch(self, url: str) -> PageContent:
        try:
            response = httpx.get(url, ...)
        except Exception as e:
            return PageContent(
                url=url,
                success=False,
                error=str(e),
                ...
            )
```

### 6.3 付费墙检测

```python
PAYWALL_INDICATORS = [
    "subscribe to continue",
    "sign up to read",
    "premium content",
    "members only",
]

def _is_paywalled(self, text: str) -> bool:
    text_lower = text.lower()
    return any(p in text_lower for p in self.PAYWALL_INDICATORS)
```

---

## 7. 未来扩展

### 7.1 PDF 研报支持

```python
class AgentBrowser:
    def _handle_pdf_link(self, url: str) -> BrowseResult | None:
        """处理 PDF 链接（如 SEC 文件）"""
        if not url.endswith(".pdf"):
            return None
        # 使用现有的 PDFExtractor
        from ..akshare.pdf_extractor import PDFExtractor
        extractor = PDFExtractor(llm_client=self._llm)
        summary = extractor.extract_summary(url)
        ...
```

### 7.2 财报电话会议记录

```python
EARNINGS_CALL_DOMAINS = [
    "seekingalpha.com/article/*earnings-call-transcript*",
    "fool.com/earnings/call-transcripts/",
]
```

### 7.3 SEC/HKEX 公告

```python
class SECFilingFetcher:
    """SEC EDGAR 公告获取"""
    BASE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
    ...

class HKEXAnnouncementFetcher:
    """港交所公告获取"""
    BASE_URL = "https://www.hkexnews.hk/"
    ...
```

---

## 8. 测试策略

### 8.1 单元测试

```python
# Mock 所有外部依赖
def test_agent_browser_depth_control(mocker):
    mock_serper = mocker.Mock()
    mock_serper.search.return_value = [...]
    
    browser = AgentBrowser(serper_client=mock_serper, ...)
    results = browser.browse("AAPL", "Apple")
    
    # 验证深度控制
    assert all(r.depth <= 2 for r in results)
```

### 8.2 集成测试

```python
@pytest.mark.integration
def test_real_search():
    """需要真实 API Key"""
    provider = HkUsTextProvider()
    items = provider.fetch_texts("AAPL", "Apple", max_items=3)
    assert len(items) > 0
```

### 8.3 本地 Mock 测试

```bash
# 录制真实响应用于本地测试
python -m src.cli record-responses --ticker AAPL --output fixtures/
```
