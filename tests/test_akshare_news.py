"""
AkShareNewsProvider 测试

测试用例：
- 单元测试：数据转换逻辑、时间过滤、辅助方法
- 集成测试：真实 API 调用（标记 @pytest.mark.integration）
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_ingestion.models import TextItem
from src.data_ingestion.text import AkShareNewsProvider


class TestAkShareNewsProviderUnit:
    """AkShareNewsProvider 单元测试"""

    def test_is_a_share_sh(self):
        """测试识别上证 A 股"""
        provider = AkShareNewsProvider()
        assert provider._is_a_share("601985.SH") is True
        assert provider._is_a_share("600150.SH") is True

    def test_is_a_share_sz(self):
        """测试识别深证 A 股"""
        provider = AkShareNewsProvider()
        assert provider._is_a_share("000001.SZ") is True
        assert provider._is_a_share("300001.SZ") is True

    def test_is_a_share_hk_rejected(self):
        """测试港股被拒绝"""
        provider = AkShareNewsProvider()
        assert provider._is_a_share("0700.HK") is False
        assert provider._is_a_share("9988.HK") is False

    def test_is_a_share_us_rejected(self):
        """测试美股被拒绝"""
        provider = AkShareNewsProvider()
        assert provider._is_a_share("AAPL") is False
        assert provider._is_a_share("TSLA") is False

    def test_extract_stock_code_sh(self):
        """测试提取上证股票代码"""
        provider = AkShareNewsProvider()
        assert provider._extract_stock_code("601985.SH") == "601985"
        assert provider._extract_stock_code("600150.SH") == "600150"

    def test_extract_stock_code_sz(self):
        """测试提取深证股票代码"""
        provider = AkShareNewsProvider()
        assert provider._extract_stock_code("000001.SZ") == "000001"
        assert provider._extract_stock_code("300001.SZ") == "300001"

    def test_parse_datetime_standard_format(self):
        """测试解析标准日期格式"""
        provider = AkShareNewsProvider()
        result = provider._parse_datetime("2024-12-20 14:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 12
        assert result.day == 20
        assert result.hour == 14
        assert result.minute == 30

    def test_parse_datetime_short_format(self):
        """测试解析简短日期格式"""
        provider = AkShareNewsProvider()
        result = provider._parse_datetime("2024-12-20 14:30")
        assert result is not None
        assert result.year == 2024
        assert result.month == 12

    def test_parse_datetime_slash_format(self):
        """测试解析斜杠日期格式"""
        provider = AkShareNewsProvider()
        result = provider._parse_datetime("2024/12/20 14:30:00")
        assert result is not None
        assert result.year == 2024

    def test_parse_datetime_invalid(self):
        """测试无效日期返回 None"""
        provider = AkShareNewsProvider()
        assert provider._parse_datetime("invalid") is None
        assert provider._parse_datetime("") is None
        assert provider._parse_datetime(None) is None

    def test_generate_summary_short_content(self):
        """测试生成摘要：短内容"""
        provider = AkShareNewsProvider()
        content = "这是一条简短的新闻内容。"
        summary = provider._generate_summary(content, "标题")
        assert summary == content

    def test_generate_summary_long_content(self):
        """测试生成摘要：长内容截断"""
        provider = AkShareNewsProvider()
        content = "这是一条" + "很长的" * 100 + "新闻内容。"
        summary = provider._generate_summary(content, "标题")
        assert len(summary) <= 210  # 200 + "..."

    def test_generate_summary_empty_content(self):
        """测试生成摘要：空内容使用标题"""
        provider = AkShareNewsProvider()
        summary = provider._generate_summary("", "新闻标题")
        assert summary == "新闻标题"

    def test_generate_summary_nan_content(self):
        """测试生成摘要：nan 内容使用标题"""
        provider = AkShareNewsProvider()
        summary = provider._generate_summary("nan", "新闻标题")
        assert summary == "新闻标题"

    def test_source_name(self):
        """测试数据源名称"""
        provider = AkShareNewsProvider()
        assert provider.get_source_name() == "东方财富"

    def test_fetch_texts_non_a_share_returns_empty(self):
        """测试非 A 股返回空列表"""
        provider = AkShareNewsProvider()

        # 港股
        result_hk = provider.fetch_texts("0700.HK", "腾讯控股")
        assert result_hk == []

        # 美股
        result_us = provider.fetch_texts("AAPL", "苹果")
        assert result_us == []

    @patch("src.data_ingestion.text.akshare_news.ak.stock_news_em")
    def test_fetch_texts_with_mock_data(self, mock_api):
        """测试使用模拟数据的完整流程"""
        # 构造模拟返回数据
        now = datetime.now()
        mock_df = pd.DataFrame({
            "新闻标题": ["中国核电发布重要公告", "核电行业利好消息"],
            "新闻内容": ["公司宣布新项目开工，预计投资100亿元。", "政策支持核电发展，行业迎来新机遇。"],
            "发布时间": [
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            "文章来源": ["东方财富", "证券时报"],
            "新闻链接": ["https://example.com/1", "https://example.com/2"],
        })
        mock_api.return_value = mock_df

        provider = AkShareNewsProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=48)

        assert len(results) == 2
        assert all(isinstance(item, TextItem) for item in results)
        assert results[0].type == "news"
        assert "核电" in results[0].title

        # 验证按时间倒序
        assert results[0].published_at >= results[1].published_at

    @patch("src.data_ingestion.text.akshare_news.ak.stock_news_em")
    def test_fetch_texts_time_filter(self, mock_api):
        """测试时间过滤"""
        now = datetime.now()
        mock_df = pd.DataFrame({
            "新闻标题": ["新闻1", "新闻2", "新闻3"],
            "新闻内容": ["内容1", "内容2", "内容3"],
            "发布时间": [
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=50)).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            "文章来源": ["东方财富", "东方财富", "东方财富"],
            "新闻链接": ["url1", "url2", "url3"],
        })
        mock_api.return_value = mock_df

        provider = AkShareNewsProvider()

        # 24 小时内只有 1 条
        results_24h = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=24)
        assert len(results_24h) == 1

        # 48 小时内有 2 条
        results_48h = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=48)
        assert len(results_48h) == 2

    @patch("src.data_ingestion.text.akshare_news.ak.stock_news_em")
    def test_fetch_texts_max_items(self, mock_api):
        """测试 max_items 限制"""
        now = datetime.now()
        mock_df = pd.DataFrame({
            "新闻标题": [f"新闻{i}" for i in range(10)],
            "新闻内容": [f"内容{i}" for i in range(10)],
            "发布时间": [
                (now - timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S")
                for i in range(10)
            ],
            "文章来源": ["东方财富"] * 10,
            "新闻链接": [f"url{i}" for i in range(10)],
        })
        mock_api.return_value = mock_df

        provider = AkShareNewsProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", max_items=3)

        assert len(results) == 3

    @patch("src.data_ingestion.text.akshare_news.ak.stock_news_em")
    def test_fetch_texts_empty_response(self, mock_api):
        """测试空响应"""
        mock_api.return_value = pd.DataFrame()

        provider = AkShareNewsProvider()
        results = provider.fetch_texts("601985.SH", "中国核电")

        assert results == []

    @patch("src.data_ingestion.text.akshare_news.ak.stock_news_em")
    def test_fetch_texts_api_error_returns_empty(self, mock_api):
        """测试 API 错误返回空列表"""
        mock_api.side_effect = Exception("Network error")

        provider = AkShareNewsProvider(max_retries=0)
        results = provider.fetch_texts("601985.SH", "中国核电")

        assert results == []

    @patch("src.data_ingestion.text.akshare_news.ak.stock_news_em")
    @patch("src.data_ingestion.text.akshare_news.time.sleep")
    def test_retry_mechanism(self, mock_sleep, mock_api):
        """测试重试机制"""
        # 前两次失败，第三次成功
        now = datetime.now()
        success_df = pd.DataFrame({
            "新闻标题": ["成功获取的新闻"],
            "新闻内容": ["内容"],
            "发布时间": [now.strftime("%Y-%m-%d %H:%M:%S")],
            "文章来源": ["东方财富"],
            "新闻链接": ["url"],
        })

        mock_api.side_effect = [
            Exception("Timeout"),
            Exception("Connection error"),
            success_df,
        ]

        provider = AkShareNewsProvider(max_retries=2, retry_delay=0.1)
        results = provider.fetch_texts("601985.SH", "中国核电")

        assert len(results) == 1
        assert mock_api.call_count == 3
        assert mock_sleep.call_count == 2

    def test_text_item_has_required_fields(self):
        """测试 TextItem 包含所有必需字段（使用 mock）"""
        with patch("src.data_ingestion.text.akshare_news.ak.stock_news_em") as mock_api:
            now = datetime.now()
            mock_df = pd.DataFrame({
                "新闻标题": ["测试新闻"],
                "新闻内容": ["这是新闻内容"],
                "发布时间": [now.strftime("%Y-%m-%d %H:%M:%S")],
                "文章来源": ["东方财富"],
                "新闻链接": ["https://example.com"],
            })
            mock_api.return_value = mock_df

            provider = AkShareNewsProvider()
            results = provider.fetch_texts("601985.SH", "中国核电")

            assert len(results) == 1
            item = results[0]

            assert item.source is not None and len(item.source) > 0
            assert item.type == "news"
            assert item.title is not None and len(item.title) > 0
            assert item.summary is not None
            assert item.published_at is not None
            assert item.url is not None


@pytest.mark.integration
class TestAkShareNewsProviderIntegration:
    """
    AkShareNewsProvider 集成测试

    这些测试会调用真实的 AkShare API。
    运行方式: pytest -m integration tests/test_akshare_news.py
    """

    def test_fetch_real_news_601985(self):
        """测试获取中国核电（601985.SH）的真实新闻"""
        provider = AkShareNewsProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=48)

        # 验证返回类型
        assert isinstance(results, list)
        assert all(isinstance(item, TextItem) for item in results)

        # 如果有数据，验证格式
        if results:
            item = results[0]
            assert item.type == "news"
            assert len(item.title) > 0
            assert item.published_at is not None
            # 验证时间在 48 小时内
            age_hours = item.get_age_hours()
            assert age_hours <= 48 + 1  # 允许 1 小时误差

    def test_fetch_real_news_600519(self):
        """测试获取贵州茅台（600519.SH）的真实新闻"""
        provider = AkShareNewsProvider()
        results = provider.fetch_texts("600519.SH", "贵州茅台", lookback_hours=48)

        assert isinstance(results, list)
        assert all(isinstance(item, TextItem) for item in results)

    def test_fetch_real_news_sz_stock(self):
        """测试获取深市股票新闻"""
        provider = AkShareNewsProvider()
        results = provider.fetch_texts("000001.SZ", "平安银行", lookback_hours=48)

        assert isinstance(results, list)
        assert all(isinstance(item, TextItem) for item in results)

    def test_real_api_max_items(self):
        """测试真实 API 的 max_items 限制"""
        provider = AkShareNewsProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", max_items=3)

        assert len(results) <= 3

    def test_real_api_sorted_by_time(self):
        """测试真实 API 返回结果按时间排序"""
        provider = AkShareNewsProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=48)

        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].published_at >= results[i + 1].published_at

    def test_real_api_source_is_set(self):
        """测试真实 API 的 source 字段"""
        provider = AkShareNewsProvider()
        results = provider.fetch_texts("601985.SH", "中国核电", lookback_hours=48)

        for item in results:
            assert item.source is not None
            assert len(item.source) > 0
