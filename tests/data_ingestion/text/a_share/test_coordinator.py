"""
AShareTextCoordinator 单元测试

测试用例：
- test_quota_calculation: 配额计算正确
- test_sh_ticker_uses_sse: 沪市股票使用 SSE 互动
- test_sz_ticker_uses_cninfo: 深市股票使用巨潮互动易
- test_graceful_degradation: 单一数据源失败不影响其他
- test_deduplication: 去重逻辑正确
- test_sorting: 排序符合优先级
- test_market_check: 非 A 股返回空列表
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Create mock akshare module before importing the coordinator
mock_akshare = MagicMock()
sys.modules["akshare"] = mock_akshare

from src.config.models import AShareTextSourceConfig
from src.data_ingestion.models import TextItem
from src.data_ingestion.text.a_share.coordinator import AShareTextCoordinator
from src.data_ingestion.text.models import TextSourceType


@pytest.fixture
def default_config() -> AShareTextSourceConfig:
    """创建默认配置"""
    return AShareTextSourceConfig(
        enabled_sources=["research", "irm", "rating", "news"],
        quota_weights={
            "research": 4,
            "irm": 3,
            "rating": 2,
            "news": 3,
        },
    )


@pytest.fixture
def coordinator(default_config: AShareTextSourceConfig) -> AShareTextCoordinator:
    """创建 AShareTextCoordinator 实例"""
    return AShareTextCoordinator(config=default_config)


@pytest.fixture
def mock_research_data() -> pd.DataFrame:
    """创建模拟的研报数据"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "日期": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d"),
            ],
            "机构名称": ["中信证券", "华泰证券"],
            "报告标题": ["核电行业深度报告", "电力板块投资策略"],
            "东财评级": ["买入", "增持"],
            "研究员": ["张三", "李四"],
            "研报链接": ["http://example.com/1", "http://example.com/2"],
        }
    )


@pytest.fixture
def mock_news_data() -> pd.DataFrame:
    """创建模拟的新闻数据"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "发布时间": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            "新闻标题": ["中国核电最新动态", "电力行业新政策"],
            "新闻内容": ["这是一条关于核电的新闻", "这是一条关于电力行业的新闻"],
            "文章来源": ["东方财富", "新浪财经"],
            "新闻链接": ["http://news.com/1", "http://news.com/2"],
        }
    )


@pytest.fixture
def mock_sse_qa_data() -> pd.DataFrame:
    """创建模拟的上证e互动数据"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "提问时间": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            "问题": ["公司的核电机组核准进展如何？"],
            "回复时间": [(now - timedelta(hours=0.5)).strftime("%Y-%m-%d %H:%M:%S")],
            "答复": ["公司目前有多个核电机组正在建设中。"],
        }
    )


@pytest.fixture
def mock_cninfo_questions_data() -> pd.DataFrame:
    """创建模拟的巨潮互动易问题数据"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "提问日期": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d"),
            ],
            "问题内容": ["公司的分红政策是怎样的？"],
            "提问者": ["投资者A"],
            "关注数": [10],
        }
    )


@pytest.fixture
def mock_cninfo_answers_data() -> pd.DataFrame:
    """创建模拟的巨潮互动易回答数据"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "回答日期": [
                (now - timedelta(hours=0.5)).strftime("%Y-%m-%d"),
            ],
            "问题内容": ["公司的分红政策是怎样的？"],
            "回答内容": ["公司坚持稳定的分红政策。"],
            "回答者": ["董秘"],
        }
    )


@pytest.fixture
def mock_rating_data() -> pd.DataFrame:
    """创建模拟的机构评级数据"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "日期": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d"),
            ],
            "机构名称": ["中金公司"],
            "评级": ["买入"],
            "评级变动": ["上调"],
            "分析师": ["王五"],
            "研报标题": ["核电景气上行"],
            "目标价": ["12.00"],
        }
    )


class TestQuotaCalculation:
    """配额计算测试"""

    def test_quota_calculation_basic(self, coordinator: AShareTextCoordinator):
        """测试基本配额计算"""
        quotas = coordinator._calculate_quotas(max_items=12)

        # 权重总和 4+3+2+3=12
        # research: 12 * 4/12 = 4
        # irm: 12 * 3/12 = 3
        # rating: 12 * 2/12 = 2
        # news: 12 * 3/12 = 3
        assert quotas["research"] == 4
        assert quotas["irm"] == 3
        assert quotas["rating"] == 2
        assert quotas["news"] == 3

    def test_quota_calculation_with_rounding(self, coordinator: AShareTextCoordinator):
        """测试配额计算的舍入处理"""
        quotas = coordinator._calculate_quotas(max_items=10)

        # 权重总和 4+3+2+3=12
        # research: round(10 * 4/12) = round(3.33) = 3
        # irm: round(10 * 3/12) = round(2.5) = 2 or 3
        # rating: round(10 * 2/12) = round(1.67) = 2
        # news: round(10 * 3/12) = round(2.5) = 2 or 3

        # 总和应该等于 max_items
        assert sum(quotas.values()) == 10

        # 权重最高的应该获得最多配额
        assert quotas["research"] >= quotas["rating"]

    def test_quota_calculation_partial_sources(self):
        """测试部分数据源启用时的配额计算"""
        config = AShareTextSourceConfig(
            enabled_sources=["research", "news"],
            quota_weights={"research": 4, "news": 3},
        )
        coordinator = AShareTextCoordinator(config=config)

        quotas = coordinator._calculate_quotas(max_items=7)

        # 只有两个数据源，权重总和 4+3=7
        assert quotas["research"] == 4
        assert quotas["news"] == 3
        assert "irm" not in quotas
        assert "rating" not in quotas

    def test_quota_calculation_empty_sources(self):
        """测试无启用数据源时的配额计算"""
        config = AShareTextSourceConfig(
            enabled_sources=[],
            quota_weights={},
        )
        coordinator = AShareTextCoordinator(config=config)

        quotas = coordinator._calculate_quotas(max_items=10)

        assert quotas == {}


class TestMarketSelection:
    """市场选择测试"""

    def test_sh_ticker_uses_sse(self, coordinator: AShareTextCoordinator):
        """测试沪市股票使用 SSE 互动"""
        fetcher = coordinator._get_irm_fetcher("601985.SH")

        assert fetcher is coordinator._sse_irm_fetcher
        assert coordinator._get_irm_source_name("601985.SH") == "上证e互动"

    def test_sz_ticker_uses_cninfo(self, coordinator: AShareTextCoordinator):
        """测试深市股票使用巨潮互动易"""
        fetcher = coordinator._get_irm_fetcher("000001.SZ")

        assert fetcher is coordinator._cninfo_irm_fetcher
        assert coordinator._get_irm_source_name("000001.SZ") == "巨潮互动易"

    def test_market_check_rejects_non_a_share(self, coordinator: AShareTextCoordinator):
        """测试非 A 股应返回空列表"""
        # 港股
        results_hk = coordinator.fetch_texts(
            ticker="0700.HK",
            name="腾讯控股",
            lookback_hours=48,
            max_items=10,
        )
        assert results_hk == []

        # 美股
        results_us = coordinator.fetch_texts(
            ticker="AAPL",
            name="Apple",
            lookback_hours=48,
            max_items=10,
        )
        assert results_us == []

    def test_supports_market(self, coordinator: AShareTextCoordinator):
        """测试市场支持判断"""
        assert coordinator.supports_market("601985.SH") is True
        assert coordinator.supports_market("000001.SZ") is True
        assert coordinator.supports_market("0700.HK") is False
        assert coordinator.supports_market("AAPL") is False


class TestGracefulDegradation:
    """优雅降级测试"""

    def test_single_source_failure_doesnt_affect_others(
        self, coordinator: AShareTextCoordinator
    ):
        """测试单一数据源失败不影响其他"""
        now = datetime.now()

        # 研报失败
        mock_akshare.stock_research_report_em.side_effect = Exception("研报 API 错误")

        # 新闻正常
        mock_akshare.stock_news_em.return_value = pd.DataFrame(
            {
                "发布时间": [(now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")],
                "新闻标题": ["测试新闻"],
                "新闻内容": ["测试内容"],
                "文章来源": ["东方财富"],
                "新闻链接": ["http://example.com"],
            }
        )

        # 互动易正常
        mock_akshare.stock_sns_sseinfo.return_value = pd.DataFrame(
            {
                "提问时间": [(now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")],
                "问题": ["测试问题"],
                "回复时间": [(now - timedelta(hours=0.5)).strftime("%Y-%m-%d %H:%M:%S")],
                "答复": ["测试回复"],
            }
        )

        # 评级正常
        mock_akshare.stock_institute_recommend_detail.return_value = pd.DataFrame(
            {
                "日期": [(now - timedelta(hours=1)).strftime("%Y-%m-%d")],
                "机构名称": ["测试机构"],
                "评级": ["买入"],
                "评级变动": ["上调"],
                "分析师": ["测试分析师"],
                "研报标题": ["测试研报"],
                "目标价": ["10.00"],
            }
        )

        results = coordinator.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        # 应该有数据返回（来自新闻、互动易、评级）
        assert len(results) > 0

        # 检查统计信息
        stats = coordinator.get_fetch_stats()
        assert stats["research"]["failure"] >= 1

        # 清理 side_effect
        mock_akshare.stock_research_report_em.side_effect = None

    def test_all_sources_failure_returns_empty(
        self, coordinator: AShareTextCoordinator
    ):
        """测试所有数据源失败时返回空列表"""
        mock_akshare.stock_research_report_em.side_effect = Exception("研报错误")
        mock_akshare.stock_news_em.side_effect = Exception("新闻错误")
        mock_akshare.stock_sns_sseinfo.side_effect = Exception("互动错误")
        mock_akshare.stock_institute_recommend_detail.side_effect = Exception("评级错误")

        results = coordinator.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        assert results == []

        # 清理 side_effects
        mock_akshare.stock_research_report_em.side_effect = None
        mock_akshare.stock_news_em.side_effect = None
        mock_akshare.stock_sns_sseinfo.side_effect = None
        mock_akshare.stock_institute_recommend_detail.side_effect = None


class TestDeduplication:
    """去重逻辑测试"""

    def test_deduplication_same_title(self, coordinator: AShareTextCoordinator):
        """测试相同标题去重"""
        now = datetime.now()
        items = [
            TextItem(
                source="来源1",
                type="news",
                title="这是一个测试标题",
                summary="摘要1",
                published_at=now,
            ),
            TextItem(
                source="来源2",
                type="news",
                title="这是一个测试标题",  # 相同标题
                summary="摘要2",
                published_at=now - timedelta(hours=1),
            ),
        ]

        result = coordinator._deduplicate(items)

        assert len(result) == 1
        assert result[0].source == "来源1"  # 保留第一个

    def test_deduplication_similar_title(self, coordinator: AShareTextCoordinator):
        """测试相似标题去重"""
        now = datetime.now()
        items = [
            TextItem(
                source="来源1",
                type="news",
                title="中国核电发布最新季度报告",
                summary="摘要1",
                published_at=now,
            ),
            TextItem(
                source="来源2",
                type="news",
                title="中国核电发布最新季度报告公告",  # 相似标题
                summary="摘要2",
                published_at=now - timedelta(hours=1),
            ),
        ]

        result = coordinator._deduplicate(items)

        # 相似度超过阈值应该去重
        assert len(result) == 1

    def test_deduplication_same_summary(self, coordinator: AShareTextCoordinator):
        """测试相同摘要去重"""
        now = datetime.now()
        items = [
            TextItem(
                source="来源1",
                type="news",
                title="标题1",
                summary="这是完全相同的摘要内容",
                published_at=now,
            ),
            TextItem(
                source="来源2",
                type="news",
                title="标题2",
                summary="这是完全相同的摘要内容",  # 相同摘要
                published_at=now - timedelta(hours=1),
            ),
        ]

        result = coordinator._deduplicate(items)

        assert len(result) == 1

    def test_deduplication_different_content(self, coordinator: AShareTextCoordinator):
        """测试不同内容不会被去重"""
        now = datetime.now()
        items = [
            TextItem(
                source="来源1",
                type="news",
                title="中国核电季度报告",
                summary="摘要1",
                published_at=now,
            ),
            TextItem(
                source="来源2",
                type="news",
                title="电力行业新政策",  # 不同标题
                summary="摘要2",  # 不同摘要
                published_at=now - timedelta(hours=1),
            ),
        ]

        result = coordinator._deduplicate(items)

        assert len(result) == 2


class TestSorting:
    """排序测试"""

    def test_sorting_by_source_priority(self, coordinator: AShareTextCoordinator):
        """测试按数据源优先级排序"""
        now = datetime.now()
        items = [
            TextItem(
                source="东方财富",
                type="news",
                title="新闻标题",
                summary="新闻摘要",
                published_at=now,
            ),
            TextItem(
                source="中信证券",
                type="research",
                title="研报标题",
                summary="评级: 买入 | 机构: 中信证券",
                published_at=now,
            ),
            TextItem(
                source="上证e互动",
                type="news",
                title="[投资者提问] 问题内容",
                summary="问: 问题\n答: 回答",
                published_at=now,
            ),
        ]

        result = coordinator._sort_by_relevance(items)

        # 研报应该排第一
        assert result[0].type == "research"
        # 互动易应该排第二
        assert "[投资者提问]" in result[1].title
        # 新闻应该排最后
        assert result[2].source == "东方财富"

    def test_sorting_by_time_within_same_type(
        self, coordinator: AShareTextCoordinator
    ):
        """测试同类型按时间排序"""
        now = datetime.now()
        items = [
            TextItem(
                source="东方财富",
                type="news",
                title="新闻标题1",
                summary="摘要1",
                published_at=now - timedelta(hours=2),
            ),
            TextItem(
                source="新浪财经",
                type="news",
                title="新闻标题2",
                summary="摘要2",
                published_at=now - timedelta(hours=1),  # 更新
            ),
            TextItem(
                source="凤凰财经",
                type="news",
                title="新闻标题3",
                summary="摘要3",
                published_at=now,  # 最新
            ),
        ]

        result = coordinator._sort_by_relevance(items)

        # 同类型内应该按时间倒序
        assert result[0].title == "新闻标题3"
        assert result[1].title == "新闻标题2"
        assert result[2].title == "新闻标题1"


class TestSourceTypeInference:
    """数据源类型推断测试"""

    def test_infer_irm_from_source(self, coordinator: AShareTextCoordinator):
        """测试从 source 推断互动易类型"""
        now = datetime.now()

        item = TextItem(
            source="上证e互动",
            type="news",
            title="问答标题",
            summary="问答摘要",
            published_at=now,
        )

        assert coordinator._infer_source_type(item) == "irm"

    def test_infer_irm_from_title_prefix(self, coordinator: AShareTextCoordinator):
        """测试从标题前缀推断互动易类型"""
        now = datetime.now()

        item = TextItem(
            source="其他来源",
            type="news",
            title="[投资者提问] 公司业绩如何",
            summary="问答摘要",
            published_at=now,
        )

        assert coordinator._infer_source_type(item) == "irm"

    def test_infer_rating_from_title(self, coordinator: AShareTextCoordinator):
        """测试从标题推断评级类型"""
        now = datetime.now()

        # 文字标签
        item1 = TextItem(
            source="中金公司",
            type="research",
            title="[上调] 核电行业投资评级",
            summary="评级: 买入 | 变动: 上调",
            published_at=now,
        )
        assert coordinator._infer_source_type(item1) == "rating"

        # emoji 标签
        item2 = TextItem(
            source="华泰证券",
            type="research",
            title="📈[上调→买入] 核电景气上行",
            summary="评级摘要",
            published_at=now,
        )
        assert coordinator._infer_source_type(item2) == "rating"

    def test_infer_research_type(self, coordinator: AShareTextCoordinator):
        """测试推断研报类型"""
        now = datetime.now()

        item = TextItem(
            source="中信证券",
            type="research",
            title="中国核电深度报告",
            summary="机构观点分析",
            published_at=now,
        )

        assert coordinator._infer_source_type(item) == "research"

    def test_infer_news_type(self, coordinator: AShareTextCoordinator):
        """测试推断新闻类型"""
        now = datetime.now()

        item = TextItem(
            source="东方财富",
            type="news",
            title="中国核电最新动态",
            summary="新闻内容",
            published_at=now,
        )

        assert coordinator._infer_source_type(item) == "news"


class TestTitleSimilarity:
    """标题相似度计算测试"""

    def test_identical_titles(self, coordinator: AShareTextCoordinator):
        """测试相同标题相似度为 1"""
        similarity = coordinator._calculate_title_similarity(
            "中国核电季度报告",
            "中国核电季度报告",
        )
        assert similarity == 1.0

    def test_different_titles(self, coordinator: AShareTextCoordinator):
        """测试完全不同标题相似度接近 0"""
        similarity = coordinator._calculate_title_similarity(
            "中国核电季度报告",
            "电力行业新政策发布",
        )
        assert similarity < 0.5

    def test_similar_titles(self, coordinator: AShareTextCoordinator):
        """测试相似标题相似度较高"""
        similarity = coordinator._calculate_title_similarity(
            "中国核电2024年一季度报告",
            "中国核电2024年一季度报告发布",
        )
        assert similarity > 0.8

    def test_empty_title(self, coordinator: AShareTextCoordinator):
        """测试空标题相似度为 0"""
        assert coordinator._calculate_title_similarity("", "标题") == 0.0
        assert coordinator._calculate_title_similarity("标题", "") == 0.0
        assert coordinator._calculate_title_similarity("", "") == 0.0


class TestSourceEnabled:
    """数据源启用检查测试"""

    def test_source_enabled(self, coordinator: AShareTextCoordinator):
        """测试数据源启用检查"""
        assert coordinator._is_source_enabled("research") is True
        assert coordinator._is_source_enabled("irm") is True
        assert coordinator._is_source_enabled("rating") is True
        assert coordinator._is_source_enabled("news") is True

    def test_source_disabled(self):
        """测试数据源禁用"""
        config = AShareTextSourceConfig(
            enabled_sources=["research", "news"],
            quota_weights={"research": 4, "news": 3},
        )
        coordinator = AShareTextCoordinator(config=config)

        assert coordinator._is_source_enabled("research") is True
        assert coordinator._is_source_enabled("news") is True
        assert coordinator._is_source_enabled("irm") is False
        assert coordinator._is_source_enabled("rating") is False


class TestMiscellaneous:
    """其他测试"""

    def test_get_source_name(self, coordinator: AShareTextCoordinator):
        """测试获取数据源名称"""
        assert coordinator.get_source_name() == "a_share_coordinator"

    def test_get_supported_source_types(self, coordinator: AShareTextCoordinator):
        """测试获取支持的数据源类型"""
        types = coordinator.get_supported_source_types()

        assert TextSourceType.RESEARCH in types
        assert TextSourceType.IRM in types
        assert TextSourceType.RATING in types
        assert TextSourceType.NEWS in types

    def test_get_and_reset_stats(self, coordinator: AShareTextCoordinator):
        """测试获取和重置统计"""
        stats = coordinator.get_fetch_stats()

        assert "research" in stats
        assert "irm" in stats
        assert "rating" in stats
        assert "news" in stats

        coordinator.reset_stats()
        stats = coordinator.get_fetch_stats()

        assert stats["research"]["success"] == 0
        assert stats["research"]["failure"] == 0

    def test_extract_symbol(self, coordinator: AShareTextCoordinator):
        """测试 ticker 代码提取"""
        assert coordinator.extract_symbol("601985.SH") == "601985"
        assert coordinator.extract_symbol("000001.SZ") == "000001"

    def test_detect_market(self, coordinator: AShareTextCoordinator):
        """测试市场检测"""
        assert coordinator.detect_market("601985.SH") == "a_share"
        assert coordinator.detect_market("000001.SZ") == "a_share"
        assert coordinator.detect_market("0700.HK") == "hk"
        assert coordinator.detect_market("AAPL") == "us"


class TestIntegration:
    """集成测试"""

    def test_fetch_texts_integration(
        self,
        coordinator: AShareTextCoordinator,
        mock_research_data: pd.DataFrame,
        mock_news_data: pd.DataFrame,
        mock_sse_qa_data: pd.DataFrame,
        mock_rating_data: pd.DataFrame,
    ):
        """测试完整的 fetch_texts 流程"""
        mock_akshare.stock_research_report_em.return_value = mock_research_data
        mock_akshare.stock_news_em.return_value = mock_news_data
        mock_akshare.stock_sns_sseinfo.return_value = mock_sse_qa_data
        mock_akshare.stock_institute_recommend_detail.return_value = mock_rating_data

        results = coordinator.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        assert len(results) > 0
        assert len(results) <= 10
        assert all(isinstance(item, TextItem) for item in results)

    def test_fetch_texts_respects_max_items(
        self,
        coordinator: AShareTextCoordinator,
        mock_research_data: pd.DataFrame,
        mock_news_data: pd.DataFrame,
        mock_sse_qa_data: pd.DataFrame,
        mock_rating_data: pd.DataFrame,
    ):
        """测试 max_items 限制"""
        mock_akshare.stock_research_report_em.return_value = mock_research_data
        mock_akshare.stock_news_em.return_value = mock_news_data
        mock_akshare.stock_sns_sseinfo.return_value = mock_sse_qa_data
        mock_akshare.stock_institute_recommend_detail.return_value = mock_rating_data

        results = coordinator.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=3,
        )

        assert len(results) <= 3
