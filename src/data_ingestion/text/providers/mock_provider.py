"""
Mock 数据提供者

用于 MVP 阶段快速验证完整流水线、单元测试和集成测试、
无网络环境下的开发调试、以及演示和文档示例。
"""
import random
from datetime import datetime, timedelta
from typing import Literal

from .base import DataProvider, ProviderRegistry, ProviderType
from ...models import TextItem


@ProviderRegistry.register(ProviderType.MOCK)
class MockProvider(DataProvider):
    """Mock 数据提供者"""

    provider_type = ProviderType.MOCK
    supported_markets: list[Literal["a_share", "hk", "us"]] = ["a_share", "hk", "us"]

    # 情绪词汇库，用于生成模拟新闻内容
    SENTIMENT_VOCABULARY = {
        "panic": {  # 恐慌 0-20
            "keywords": ["崩盘", "危机", "暴跌", "爆雷", "不可持续"],
            "templates": [
                "{name}面临严重危机，市场担忧加剧",
                "分析师警告：{name}存在崩盘风险",
                "{name}遭遇暴跌，投资者恐慌情绪蔓延",
            ],
        },
        "pessimistic": {  # 悲观 21-40
            "keywords": ["成本压力", "下调", "不及预期", "汇率风险", "增长放缓"],
            "templates": [
                "{name}业绩不及预期，多家机构下调评级",
                "成本压力持续，{name}利润率承压",
                "{name}面临增长放缓困境，前景堪忧",
            ],
        },
        "neutral": {  # 中性 41-60
            "keywords": ["观望", "等待", "price-in", "多空平衡", "维持评级"],
            "templates": [
                "{name}短期多空交织，建议观望",
                "市场已充分定价，{name}维持中性评级",
                "{name}处于多空平衡状态，等待催化剂",
            ],
        },
        "optimistic": {  # 乐观 61-80
            "keywords": ["超预期", "上调目标价", "景气度", "增长动力", "买入"],
            "templates": [
                "{name}业绩超预期，机构纷纷上调目标价",
                "行业景气度持续，{name}受益明显",
                "{name}增长动力强劲，维持买入评级",
            ],
        },
        "euphoric": {  # 狂热 81-100
            "keywords": ["历史性机遇", "无限空间", "颠覆", "新纪元", "爆发式增长"],
            "templates": [
                "{name}迎来历史性机遇，增长空间无限",
                "颠覆性变革来临，{name}将开启新纪元",
                "{name}有望实现爆发式增长，强烈推荐",
            ],
        },
    }

    # 研报来源
    RESEARCH_PROVIDERS = [
        "中信证券",
        "华泰证券",
        "海通证券",
        "国泰君安",
        "招商证券",
        "Morgan Stanley",
        "Goldman Sachs",
        "JP Morgan",
        "UBS",
    ]

    # 新闻来源
    NEWS_SOURCES = {
        "a_share": ["东方财富", "新浪财经", "同花顺", "证券时报"],
        "hk": ["香港经济日报", "信报", "Bloomberg"],
        "us": ["Bloomberg", "Reuters", "CNBC", "WSJ"],
    }

    def fetch_news(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """生成模拟新闻数据"""

        market = self._detect_market(ticker)
        sources = self.NEWS_SOURCES.get(market, self.NEWS_SOURCES["a_share"])

        # 随机选择一个情绪倾向（模拟真实市场情况）
        sentiment_key = random.choice(list(self.SENTIMENT_VOCABULARY.keys()))
        sentiment_data = self.SENTIMENT_VOCABULARY[sentiment_key]

        texts = []
        num_items = random.randint(3, min(max_items, 8))

        for i in range(num_items):
            # 随机生成发布时间（在 lookback_hours 内）
            hours_ago = random.uniform(1, lookback_hours)
            published_at = datetime.now() - timedelta(hours=hours_ago)

            # 随机选择模板和关键词
            template = random.choice(sentiment_data["templates"])
            keyword = random.choice(sentiment_data["keywords"])

            title = template.format(name=name)
            summary = f"{title}。分析认为，{keyword}是当前市场关注的核心因素。"

            texts.append(
                TextItem(
                    source=random.choice(sources),
                    type="news",
                    title=title,
                    summary=summary,
                    published_at=published_at,
                    url=f"https://mock.example.com/news/{ticker}/{i}",
                )
            )

        # 按时间排序（最新的在前）
        texts.sort(key=lambda x: x.published_at, reverse=True)

        return texts

    def fetch_research(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """生成模拟研报数据"""

        market = self._detect_market(ticker)

        # 根据市场选择券商
        if market == "a_share":
            providers = [p for p in self.RESEARCH_PROVIDERS if not p[0].isupper()]
        else:
            providers = [p for p in self.RESEARCH_PROVIDERS if p[0].isupper()]

        if not providers:
            providers = self.RESEARCH_PROVIDERS

        texts = []
        num_items = random.randint(2, min(max_items, 5))

        for i in range(num_items):
            provider = random.choice(providers)
            hours_ago = random.uniform(1, lookback_hours)
            published_at = datetime.now() - timedelta(hours=hours_ago)

            # 研报标题模板
            title_templates = [
                f"【{provider}】{name}深度报告：行业龙头地位稳固",
                f"【{provider}】{name}投资价值分析",
                f"【{provider}】{name}跟踪报告：业绩符合预期",
                f"【{provider}】{name}首次覆盖：长期成长空间广阔",
            ]

            title = random.choice(title_templates)

            # 研报摘要模板
            summary_templates = [
                f"投资建议：我们维持对{name}的「买入」评级。核心逻辑：1）行业景气度持续；2）公司竞争优势明显；3）估值具有吸引力。风险提示：宏观经济波动、行业竞争加剧。",
                f"核心观点：{name}作为行业龙头，受益于政策支持和需求增长。我们预计公司未来三年复合增长率达15%以上。目标价上调10%。",
                f"投资要点：1）{name}基本面稳健，业绩增长确定性高；2）估值处于历史低位，具有安全边际；3）催化剂明确，建议积极配置。",
            ]

            summary = random.choice(summary_templates)

            texts.append(
                TextItem(
                    source=provider,
                    type="research",
                    title=title,
                    summary=summary,
                    published_at=published_at,
                    url=f"https://mock.example.com/research/{ticker}/{i}",
                )
            )

        texts.sort(key=lambda x: x.published_at, reverse=True)

        return texts

    def is_available(self) -> bool:
        """Mock 提供者始终可用"""
        return True


if __name__ == "__main__":
    provider = MockProvider()

    print("=" * 60)
    print("测试 A 股新闻")
    print("=" * 60)
    news = provider.fetch_news("601985.SH", "中国核电")
    for item in news:
        print(f"[{item.source}] {item.title}")
        print(f"  摘要: {item.summary[:50]}...")
        print(f"  时间: {item.published_at}")
        print()

    print("=" * 60)
    print("测试港股研报")
    print("=" * 60)
    research = provider.fetch_research("0700.HK", "腾讯控股")
    for item in research:
        print(f"[{item.source}] {item.title}")
        print(f"  摘要: {item.summary[:50]}...")
        print()
