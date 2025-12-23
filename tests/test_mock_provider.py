"""
MockTextProvider 单元测试

测试用例：
- test_fetch_returns_text_items: 测试返回正确的 TextItem 列表
- test_max_items_limit: 测试 max_items 参数生效
- test_lookback_hours_filter: 测试 lookback_hours 参数生效
- test_unknown_ticker_returns_default: 测试未知 ticker 返回默认数据
- test_results_sorted_by_time: 测试结果按时间降序排列
- test_contains_both_research_and_news: 测试同时包含研报和新闻
- test_source_name: 测试数据源名称
"""
from datetime import datetime, timedelta

import pytest

from src.data_ingestion.models import TextItem
from src.data_ingestion.text import MockTextProvider


class TestMockTextProvider:
    """MockTextProvider 测试类"""

    def test_fetch_returns_text_items(self):
        """测试返回正确的 TextItem 列表"""
        provider = MockTextProvider()
        results = provider.fetch_texts("601985.SH", "中国核电")

        assert len(results) > 0
        assert all(isinstance(item, TextItem) for item in results)

    def test_max_items_limit(self):
        """测试 max_items 参数生效"""
        provider = MockTextProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", max_items=2)

        assert len(results) <= 2

    def test_lookback_hours_filter(self):
        """测试 lookback_hours 参数生效"""
        provider = MockTextProvider()
        # 使用较短的 lookback_hours 来过滤掉部分数据
        results = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=10)

        # 验证所有返回的数据都在时间窗口内（加一点容差避免边界问题）
        cutoff = datetime.now() - timedelta(hours=10, seconds=5)
        for item in results:
            assert item.published_at >= cutoff

        # 验证确实过滤掉了一些数据（hours_ago > 10 的数据应该被过滤）
        all_results = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=48)
        assert len(results) < len(all_results)

    def test_unknown_ticker_returns_default(self):
        """测试未知 ticker 返回默认数据"""
        provider = MockTextProvider()
        results = provider.fetch_texts("UNKNOWN.XX", "未知标的")

        assert len(results) > 0

    def test_results_sorted_by_time(self):
        """测试结果按时间降序排列"""
        provider = MockTextProvider()
        results = provider.fetch_texts("601985.SH", "中国核电")

        for i in range(len(results) - 1):
            assert results[i].published_at >= results[i + 1].published_at

    def test_contains_both_research_and_news(self):
        """测试同时包含研报和新闻"""
        provider = MockTextProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", max_items=10)

        types = {item.type for item in results}
        assert "research" in types
        assert "news" in types

    def test_source_name(self):
        """测试数据源名称"""
        provider = MockTextProvider()
        assert provider.get_source_name() == "mock"

    def test_aapl_data_exists(self):
        """测试 AAPL 数据存在"""
        provider = MockTextProvider()
        results = provider.fetch_texts("AAPL", "Apple")

        assert len(results) > 0
        # AAPL 应有英文数据
        assert any("Apple" in item.title or "iPhone" in item.title for item in results)

    def test_different_tickers_return_different_data(self):
        """测试不同标的返回不同数据"""
        provider = MockTextProvider()

        results_nuclear = provider.fetch_texts("601985.SH", "中国核电")
        results_ship = provider.fetch_texts("600150.SH", "中国船舶")

        # 标题应该不同
        titles_nuclear = {item.title for item in results_nuclear}
        titles_ship = {item.title for item in results_ship}

        assert titles_nuclear != titles_ship

    def test_data_type_filter(self):
        """测试数据类型过滤"""
        # 只获取研报
        provider_research = MockTextProvider(data_type="research")
        results_research = provider_research.fetch_texts("601985.SH", "中国核电")

        assert all(item.type == "research" for item in results_research)

        # 只获取新闻
        provider_news = MockTextProvider(data_type="news")
        results_news = provider_news.fetch_texts("601985.SH", "中国核电")

        assert all(item.type == "news" for item in results_news)

    def test_text_item_has_required_fields(self):
        """测试 TextItem 包含所有必需字段"""
        provider = MockTextProvider()
        results = provider.fetch_texts("601985.SH", "中国核电")

        for item in results:
            assert item.source is not None and len(item.source) > 0
            assert item.type in ("research", "news")
            assert item.title is not None and len(item.title) > 0
            assert item.summary is not None
            assert item.published_at is not None
            assert item.url is not None

    def test_hk_stock_data_exists(self):
        """测试港股数据存在"""
        provider = MockTextProvider()
        results = provider.fetch_texts("0700.HK", "腾讯控股")

        assert len(results) > 0
        # 腾讯数据应包含中英文
        has_chinese = any("腾讯" in item.title or "游戏" in item.title for item in results)
        has_english = any("Tencent" in item.title for item in results)

        assert has_chinese or has_english

    def test_get_available_tickers(self):
        """测试获取可用标的列表"""
        tickers = MockTextProvider.get_available_tickers()

        assert "601985.SH" in tickers
        assert "600150.SH" in tickers
        assert "0700.HK" in tickers
        assert "AAPL" in tickers
        assert "_default_" in tickers
