"""
Mock 文本数据提供者 - 用于 MVP 阶段开发测试

提供预设的模拟数据，让流水线可以在不依赖外部数据源的情况下完整运行。
"""
import logging
from datetime import datetime, timedelta
from typing import ClassVar

from ..models import TextItem
from .base import TextProvider

logger = logging.getLogger(__name__)


class MockTextProvider(TextProvider):
    """
    Mock 文本数据提供者，用于开发测试

    预设了多个标的的模拟数据，覆盖不同情绪倾向和来源类型。
    """

    # 预设的模拟数据，按 ticker 分类
    # 每个标的包含不同情绪倾向（乐观/中性/悲观）和来源（研报/新闻）
    MOCK_DATA: ClassVar[dict[str, list[dict]]] = {
        # ============================================
        # 中国核电 601985.SH
        # ============================================
        "601985.SH": [
            # 乐观 - 研报
            {
                "source": "中信证券",
                "type": "research",
                "title": "中国核电：AI算力驱动电力需求增长，核电龙头迎历史机遇",
                "summary": (
                    "核电作为稳定基荷电力，将充分受益于AI数据中心扩张带来的电力需求增长。"
                    "公司作为国内核电运营龙头，在建机组规模行业领先，"
                    "预计2025-2027年将迎来机组集中投产期，业绩增长确定性高。"
                    "维持「买入」评级，目标价12元。"
                ),
                "hours_ago": 4,
            },
            {
                "source": "华泰证券",
                "type": "research",
                "title": "中国核电深度报告：核电重启加速，成长空间打开",
                "summary": (
                    "核电审批重启后进入加速期，公司储备项目充足。"
                    "核电利用小时数高于火电，盈利能力稳定且可预测。"
                    "AI算力发展对稳定电源需求增加，核电价值重估进行时。"
                    "上调目标价至11.5元，维持「买入」评级。"
                ),
                "hours_ago": 12,
            },
            # 中性 - 研报
            {
                "source": "海通证券",
                "type": "research",
                "title": "中国核电：业绩稳健增长，关注新机组投产节奏",
                "summary": (
                    "公司三季报业绩符合预期，在运机组发电量稳步增长。"
                    "新机组建设进度正常，但需关注审批和建设周期的不确定性。"
                    "当前估值处于历史中枢水平，维持「增持」评级。"
                ),
                "hours_ago": 24,
            },
            # 乐观 - 新闻
            {
                "source": "东方财富",
                "type": "news",
                "title": "核电板块持续走强，机构密集调研中国核电",
                "summary": (
                    "核电板块今日延续强势，中国核电涨幅居前。"
                    "多家机构近期密集调研，看好AI算力带来的电力需求增量。"
                    "分析师普遍认为核电估值仍有提升空间。"
                ),
                "hours_ago": 2,
            },
            # 中性 - 新闻
            {
                "source": "同花顺",
                "type": "news",
                "title": "中国核电：前三季度发电量同比增长8.5%",
                "summary": (
                    "中国核电发布运营数据，前三季度累计发电量1580亿千瓦时，"
                    "同比增长8.5%。在运机组保持安全稳定运行，"
                    "平均利用小时数处于行业较高水平。"
                ),
                "hours_ago": 8,
            },
            # 悲观 - 新闻
            {
                "source": "Bloomberg",
                "type": "news",
                "title": "China Nuclear Faces Challenges from Renewable Competition",
                "summary": (
                    "China Nuclear Power Corp. may face increasing competition "
                    "from renewable energy sources as solar and wind costs continue to decline. "
                    "Some analysts suggest nuclear power's market share could be squeezed "
                    "in the long term despite near-term demand strength."
                ),
                "hours_ago": 18,
            },
        ],
        # ============================================
        # 中国船舶 600150.SH
        # ============================================
        "600150.SH": [
            # 乐观 - 研报
            {
                "source": "中信证券",
                "type": "research",
                "title": "中国船舶：全球造船周期开启，龙头价值重估",
                "summary": (
                    "全球供应链重构叠加老旧船舶更替，造船长周期已然开启。"
                    "公司作为国内船舶制造龙头，订单饱满，产能利用率高企。"
                    "战略资产应按重置成本定价，当前估值存在显著低估。"
                    "首次覆盖给予「买入」评级。"
                ),
                "hours_ago": 6,
            },
            # 中性 - 研报
            {
                "source": "Morgan Stanley",
                "type": "research",
                "title": "CSSC: Order Book Strong but Margin Pressure Persists",
                "summary": (
                    "China State Shipbuilding Corp. has a record order backlog, "
                    "but rising steel prices and labor costs may pressure margins in the near term. "
                    "The company is well-positioned for the shipbuilding upcycle, "
                    "though execution remains key. Equal-weight rating maintained."
                ),
                "hours_ago": 20,
            },
            # 悲观 - 新闻
            {
                "source": "Reuters",
                "type": "news",
                "title": "Global Shipping Slowdown Raises Concerns for Shipbuilders",
                "summary": (
                    "The global shipping industry is showing signs of cooling, "
                    "with freight rates declining from pandemic highs. "
                    "While order backlogs remain strong, some analysts worry about "
                    "potential order cancellations if economic conditions deteriorate."
                ),
                "hours_ago": 10,
            },
            # 乐观 - 新闻
            {
                "source": "东方财富",
                "type": "news",
                "title": "中国船舶获大额订单，造船景气度持续",
                "summary": (
                    "中国船舶集团近期获得多笔大额造船订单，"
                    "涵盖集装箱船、LNG运输船等高附加值船型。"
                    "业内人士表示，全球航运业复苏态势明确，"
                    "船舶制造行业景气周期有望延续至2027年。"
                ),
                "hours_ago": 5,
            },
            # 中性 - 新闻
            {
                "source": "同花顺",
                "type": "news",
                "title": "船舶制造板块震荡整理，机构观点分歧",
                "summary": (
                    "船舶制造板块今日震荡整理，中国船舶小幅收涨。"
                    "部分机构认为板块已充分反映景气预期，"
                    "也有机构坚持看好长周期逻辑，建议逢低布局。"
                ),
                "hours_ago": 3,
            },
        ],
        # ============================================
        # 腾讯控股 0700.HK
        # ============================================
        "0700.HK": [
            # 乐观 - 研报
            {
                "source": "Goldman Sachs",
                "type": "research",
                "title": "Tencent: AI Integration to Drive Next Growth Phase",
                "summary": (
                    "Tencent is well-positioned to benefit from AI integration across its ecosystem. "
                    "Gaming, advertising, and cloud businesses all have significant AI upside. "
                    "Combined with aggressive buybacks and dividend policy, "
                    "we see compelling value. Maintain Buy rating with HK$480 target."
                ),
                "hours_ago": 8,
            },
            {
                "source": "中信证券",
                "type": "research",
                "title": "腾讯控股：游戏出海+视频号商业化，增长动能充沛",
                "summary": (
                    "公司游戏业务在海外市场持续突破，多款产品表现亮眼。"
                    "视频号广告和电商商业化进展超预期，有望成为新增长极。"
                    "回购力度持续加大，股东回报提升。"
                    "维持「买入」评级，目标价450港元。"
                ),
                "hours_ago": 16,
            },
            # 中性 - 研报
            {
                "source": "华泰证券",
                "type": "research",
                "title": "腾讯控股：业绩稳健，关注监管政策动向",
                "summary": (
                    "公司三季度业绩基本符合预期，核心业务保持稳定。"
                    "游戏版号发放节奏和互联网监管政策仍需持续关注。"
                    "当前估值合理，维持「增持」评级。"
                ),
                "hours_ago": 28,
            },
            # 悲观 - 新闻
            {
                "source": "Bloomberg",
                "type": "news",
                "title": "Tencent Faces Headwinds as China Gaming Market Matures",
                "summary": (
                    "Tencent Holdings faces challenges as China's gaming market shows signs of saturation. "
                    "Domestic gaming revenue growth has slowed, and competition from ByteDance "
                    "and other players intensifies. Regulatory uncertainty also weighs on sentiment."
                ),
                "hours_ago": 6,
            },
            # 乐观 - 新闻
            {
                "source": "东方财富",
                "type": "news",
                "title": "腾讯再度大手笔回购，年内回购金额创历史新高",
                "summary": (
                    "腾讯控股今日再度回购股份，年内累计回购金额已超千亿港元。"
                    "市场人士认为，大规模回购彰显管理层对公司长期发展的信心，"
                    "也为股价提供了有力支撑。"
                ),
                "hours_ago": 2,
            },
            # 中性 - 新闻
            {
                "source": "Reuters",
                "type": "news",
                "title": "Tencent's WeChat Pay Expands Cross-Border Services",
                "summary": (
                    "Tencent's WeChat Pay is expanding its cross-border payment services, "
                    "partnering with more international merchants. "
                    "The move aims to capture growing outbound travel demand from Chinese consumers, "
                    "though revenue impact is expected to be modest."
                ),
                "hours_ago": 14,
            },
        ],
        # ============================================
        # 苹果 AAPL - 乐观
        # ============================================
        "AAPL": [
            # 乐观 - 研报
            {
                "source": "Goldman Sachs",
                "type": "research",
                "title": "Apple: AI Integration Poised to Drive Next iPhone Supercycle",
                "summary": (
                    "Apple's integration of on-device AI features in the upcoming iPhone lineup "
                    "is expected to drive a major upgrade cycle. With over 1 billion active iPhones, "
                    "even modest upgrade rates would generate substantial revenue. "
                    "Services revenue continues to grow at 20%+ annually. Buy rating, $250 target."
                ),
                "hours_ago": 5,
            },
            {
                "source": "Morgan Stanley",
                "type": "research",
                "title": "Apple: Vision Pro Opens New Revenue Stream, Maintain Overweight",
                "summary": (
                    "Apple Vision Pro launch marks the company's entry into spatial computing. "
                    "While initial volumes are modest, the long-term TAM for AR/VR is significant. "
                    "Core iPhone and Services businesses remain strong. "
                    "Overweight rating with $240 price target."
                ),
                "hours_ago": 18,
            },
            # 乐观 - 新闻
            {
                "source": "Bloomberg",
                "type": "news",
                "title": "Apple Stock Hits All-Time High on AI Optimism",
                "summary": (
                    "Apple shares reached a record high as investors bet on the company's "
                    "AI strategy driving renewed demand for iPhones and other devices. "
                    "Analysts highlight Apple's ability to monetize AI features across its ecosystem."
                ),
                "hours_ago": 2,
            },
            {
                "source": "Reuters",
                "type": "news",
                "title": "Apple Services Revenue Beats Expectations, Hits New Record",
                "summary": (
                    "Apple reported record services revenue, driven by strong App Store, "
                    "iCloud, and Apple Music subscriptions. The high-margin services segment "
                    "now accounts for over 20% of total revenue, supporting margin expansion."
                ),
                "hours_ago": 8,
            },
            # 中性 - 新闻
            {
                "source": "CNBC",
                "type": "news",
                "title": "Apple Faces Regulatory Scrutiny in EU Over App Store Policies",
                "summary": (
                    "European regulators continue to examine Apple's App Store policies, "
                    "which could impact the company's services revenue in the region. "
                    "Apple maintains its practices comply with local regulations."
                ),
                "hours_ago": 12,
            },
        ],
        # ============================================
        # 默认数据 _default_ - 中性
        # ============================================
        "_default_": [
            {
                "source": "中信证券",
                "type": "research",
                "title": "行业研究：板块估值处于历史中枢",
                "summary": (
                    "当前板块估值处于历史中枢水平，基本面保持稳定。"
                    "建议关注行业龙头的配置价值，等待催化因素出现。"
                    "维持行业「中性」评级。"
                ),
                "hours_ago": 12,
            },
            {
                "source": "华泰证券",
                "type": "research",
                "title": "行业跟踪：基本面平稳，关注政策动向",
                "summary": (
                    "行业整体运行平稳，供需格局未见明显变化。"
                    "近期政策面存在不确定性，建议投资者保持观望。"
                    "维持「增持」评级。"
                ),
                "hours_ago": 24,
            },
            {
                "source": "东方财富",
                "type": "news",
                "title": "市场观察：板块走势分化，机构观点不一",
                "summary": (
                    "今日市场走势分化，部分板块表现活跃。"
                    "分析人士建议投资者保持理性，关注个股基本面变化。"
                ),
                "hours_ago": 4,
            },
            {
                "source": "同花顺",
                "type": "news",
                "title": "行业资讯：市场情绪趋于平稳",
                "summary": (
                    "近期市场情绪趋于平稳，成交量维持在正常水平。"
                    "分析师建议投资者关注中长期配置机会。"
                ),
                "hours_ago": 8,
            },
        ],
    }


    def __init__(self, data_type: str = "all"):
        """
        初始化 Mock 数据提供者

        Args:
            data_type: 数据类型，"research"/"news"/"all"
        """
        self._data_type = data_type

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取模拟文本数据

        Args:
            ticker: 证券代码
            name: 标的名称
            lookback_hours: 回溯时间窗口（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 模拟的文本数据列表
        """
        logger.info(f"Fetching mock texts for {ticker} ({name})")

        now = datetime.now()

        # 获取该标的的模拟数据，如果没有预设则使用 _default_ 数据
        ticker_upper = ticker.upper()
        mock_data = self.MOCK_DATA.get(ticker_upper, self.MOCK_DATA.get("_default_", []))

        # 过滤数据类型
        if self._data_type != "all":
            mock_data = [d for d in mock_data if d["type"] == self._data_type]

        # 过滤时间窗口
        mock_data = [d for d in mock_data if d["hours_ago"] <= lookback_hours]

        # 构建 TextItem 列表
        text_items = []
        for data in mock_data[:max_items]:
            published_at = now - timedelta(hours=data["hours_ago"])
            item = TextItem(
                source=data["source"],
                type=data["type"],
                title=data["title"],
                summary=data["summary"],
                published_at=published_at,
                url=f"https://mock.example.com/{ticker}/{data['type']}/{data['hours_ago']}",
            )
            text_items.append(item)

        # 按发布时间倒序排列
        text_items.sort(key=lambda x: x.published_at, reverse=True)

        logger.info(f"Returned {len(text_items)} mock items for {ticker}")
        return text_items

    def get_source_name(self) -> str:
        """返回数据源名称"""
        return "mock"

    @classmethod
    def get_available_tickers(cls) -> list[str]:
        """
        获取有预设数据的标的列表

        Returns:
            list[str]: 标的代码列表
        """
        return list(cls.MOCK_DATA.keys())
