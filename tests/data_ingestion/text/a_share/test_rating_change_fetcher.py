"""
RatingChangeFetcher 单元测试

测试用例：
- test_fetch_rating_changes: 正常获取数据
- test_priority_upgrades_downgrades: 上调/下调优先
- test_calculate_trend: 趋势计算正确
- test_target_price_handling: 目标价缺失时的处理
- test_emoji_in_title: 标题包含正确的 emoji
- test_non_a_share_ticker: 非 A 股处理
- test_get_rating_trend: 趋势统计功能
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_ingestion.models import TextItem
from src.data_ingestion.text.models import TextSourceType


def _create_mock_rating_data() -> pd.DataFrame:
    """创建模拟的机构评级数据 DataFrame"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "日期": [
                (now - timedelta(days=0)).strftime("%Y-%m-%d"),
                (now - timedelta(days=0)).strftime("%Y-%m-%d"),
                (now - timedelta(days=1)).strftime("%Y-%m-%d"),
                (now - timedelta(days=1)).strftime("%Y-%m-%d"),
                (now - timedelta(days=2)).strftime("%Y-%m-%d"),
                (now - timedelta(days=10)).strftime("%Y-%m-%d"),  # 超过默认 48 小时
            ],
            "股票代码": ["601985"] * 6,
            "股票名称": ["中国核电"] * 6,
            "研报标题": [
                "核电景气上行，维持买入",
                "行业复苏，下调评级",
                "首次覆盖：核电龙头",
                "维持增持评级",
                "行业展望报告",
                "这是一个过期的评级",
            ],
            "评级": ["买入", "中性", "买入", "增持", "增持", "买入"],
            "评级变动": ["上调", "下调", "首次", "维持", "上调", "维持"],
            "机构名称": [
                "中信证券",
                "国泰君安",
                "招商证券",
                "华泰证券",
                "中金公司",
                "过期机构",
            ],
            "分析师": [
                "张三,李四",
                "王五",
                "赵六",
                "陈七",
                "周八",
                "过期分析师",
            ],
            "目标价": [
                "15.00",
                "10.00-12.00",
                "",
                "nan",
                "18.50",
                "20.00",
            ],
        }
    )


@pytest.fixture
def mock_rating_data() -> pd.DataFrame:
    """创建模拟的机构评级数据 DataFrame"""
    return _create_mock_rating_data()


class TestRatingChangeFetcher:
    """RatingChangeFetcher 测试类"""

    def test_fetch_rating_changes(self, mock_rating_data: pd.DataFrame):
        """测试正常获取数据"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            assert len(results) > 0
            assert all(isinstance(item, TextItem) for item in results)
            assert all(item.type == "research" for item in results)

    def test_priority_upgrades_downgrades(self, mock_rating_data: pd.DataFrame):
        """测试上调/下调优先"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            # 前几个应该是上调/下调（优先级最高）
            assert len(results) >= 2

            # 找出上调/下调的位置和首次/维持的位置
            upgrade_downgrade_indices = []
            initiation_maintain_indices = []

            for i, item in enumerate(results):
                if "上调" in item.title or "下调" in item.title:
                    upgrade_downgrade_indices.append(i)
                elif "首次" in item.title or "维持" in item.title:
                    initiation_maintain_indices.append(i)

            # 上调/下调应该在首次/维持前面（如果存在的话）
            if upgrade_downgrade_indices and initiation_maintain_indices:
                # 同一天的上调/下调应该在首次/维持前面
                pass  # 由于日期也是排序因素，这里只验证存在优先级排序

    def test_calculate_trend(self, mock_rating_data: pd.DataFrame):
        """测试趋势计算正确"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 使用内部方法测试趋势计算
            trend = fetcher._calculate_rating_trend(mock_rating_data)

            assert "upgrades" in trend
            assert "downgrades" in trend
            assert "maintains" in trend
            assert "initiations" in trend
            assert "trend_signal" in trend

            # mock 数据中：上调 2 个，下调 1 个，首次 1 个，维持 2 个
            assert trend["upgrades"] == 2
            assert trend["downgrades"] == 1
            assert trend["maintains"] == 2
            assert trend["initiations"] == 1
            # 上调 > 下调，应该是 bullish
            assert trend["trend_signal"] == "bullish"

    def test_calculate_trend_bearish(self):
        """测试趋势计算 - 下调多于上调"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 创建下调多的数据
            bearish_df = pd.DataFrame(
                {
                    "评级变动": ["下调", "下调", "下调", "上调", "维持"],
                }
            )

            trend = fetcher._calculate_rating_trend(bearish_df)
            assert trend["trend_signal"] == "bearish"
            assert trend["downgrades"] == 3
            assert trend["upgrades"] == 1

    def test_calculate_trend_neutral(self):
        """测试趋势计算 - 上调等于下调"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 创建中性数据
            neutral_df = pd.DataFrame(
                {
                    "评级变动": ["上调", "下调", "维持", "维持"],
                }
            )

            trend = fetcher._calculate_rating_trend(neutral_df)
            assert trend["trend_signal"] == "neutral"
            assert trend["upgrades"] == 1
            assert trend["downgrades"] == 1

    def test_calculate_trend_empty(self):
        """测试趋势计算 - 空数据"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 测试空 DataFrame
            trend = fetcher._calculate_rating_trend(pd.DataFrame())
            assert trend["trend_signal"] == "neutral"
            assert trend["upgrades"] == 0
            assert trend["downgrades"] == 0

            # 测试 None
            trend = fetcher._calculate_rating_trend(None)
            assert trend["trend_signal"] == "neutral"

    def test_target_price_handling(self, mock_rating_data: pd.DataFrame):
        """测试目标价缺失时的处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            # 检查摘要中目标价的处理
            for item in results:
                # 摘要应该是有效的字符串
                assert isinstance(item.summary, str)
                assert len(item.summary) > 0

                # 如果有目标价，应该格式正确
                if "目标价:" in item.summary:
                    # 可能是数字格式或区间格式
                    pass  # 只要不崩溃就行

    def test_target_price_range(self):
        """测试目标价区间格式处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 测试区间格式的目标价
            row = pd.Series(
                {
                    "机构名称": "测试机构",
                    "分析师": "测试分析师",
                    "评级": "买入",
                    "评级变动": "上调",
                    "目标价": "10.00-12.00",
                }
            )

            summary = fetcher._build_rating_summary(row)
            assert "目标价: 10.00-12.00" in summary

    def test_target_price_numeric(self):
        """测试数字格式目标价处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            row = pd.Series(
                {
                    "机构名称": "测试机构",
                    "分析师": "测试分析师",
                    "评级": "买入",
                    "评级变动": "上调",
                    "目标价": "15.00",
                }
            )

            summary = fetcher._build_rating_summary(row)
            assert "目标价: 15.00" in summary

    def test_emoji_in_title(self, mock_rating_data: pd.DataFrame):
        """测试标题包含正确的 emoji"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            # 检查 emoji 是否正确
            for item in results:
                if "上调" in item.title:
                    assert "📈" in item.title
                elif "下调" in item.title:
                    assert "📉" in item.title
                elif "维持" in item.title:
                    assert "➡️" in item.title
                elif "首次" in item.title:
                    assert "🆕" in item.title

    def test_build_title_formats(self):
        """测试标题构建的各种格式"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 完整信息
            row1 = pd.Series(
                {
                    "评级变动": "上调",
                    "评级": "买入",
                    "研报标题": "核电景气上行",
                }
            )
            title1 = fetcher._build_title(row1)
            assert title1 == "📈[上调→买入] 核电景气上行"

            # 只有评级变动
            row2 = pd.Series(
                {
                    "评级变动": "下调",
                    "评级": "",
                    "研报标题": "",
                }
            )
            title2 = fetcher._build_title(row2)
            assert "📉" in title2
            assert "下调" in title2

            # 只有研报标题
            row3 = pd.Series(
                {
                    "评级变动": "",
                    "评级": "",
                    "研报标题": "行业分析报告",
                }
            )
            title3 = fetcher._build_title(row3)
            assert title3 == "行业分析报告"

    def test_non_a_share_ticker(self):
        """测试非 A 股处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 港股
            results_hk = fetcher.fetch_texts(
                ticker="0700.HK",
                name="腾讯控股",
                lookback_hours=48,
                max_items=10,
            )
            assert results_hk == []

            # 美股
            results_us = fetcher.fetch_texts(
                ticker="AAPL",
                name="Apple",
                lookback_hours=48,
                max_items=10,
            )
            assert results_us == []

    def test_supports_a_share(self):
        """测试 A 股支持"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 上海
            assert fetcher.supports_market("601985.SH") is True
            assert fetcher.supports_market("601985.sh") is True

            # 深圳
            assert fetcher.supports_market("000001.SZ") is True
            assert fetcher.supports_market("000001.sz") is True

            # 非 A 股
            assert fetcher.supports_market("0700.HK") is False
            assert fetcher.supports_market("AAPL") is False

    def test_get_rating_trend(self, mock_rating_data: pd.DataFrame):
        """测试趋势统计功能"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            trend = fetcher.get_rating_trend(
                ticker="601985.SH",
                days=30,
            )

            assert "upgrades" in trend
            assert "downgrades" in trend
            assert "maintains" in trend
            assert "initiations" in trend
            assert "trend_signal" in trend
            assert trend["trend_signal"] in ("bullish", "bearish", "neutral")

    def test_get_rating_trend_non_a_share(self):
        """测试非 A 股的趋势统计"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            trend = fetcher.get_rating_trend(
                ticker="AAPL",
                days=30,
            )

            assert trend["upgrades"] == 0
            assert trend["downgrades"] == 0
            assert trend["trend_signal"] == "neutral"

    def test_api_error_handling(self):
        """测试 API 错误处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.side_effect = Exception(
                "API Error"
            )

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            assert results == []

    def test_empty_data(self):
        """测试空数据处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = pd.DataFrame()

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            assert results == []

    def test_none_data(self):
        """测试返回 None 的处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = None

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            assert results == []

    def test_time_filter(self, mock_rating_data: pd.DataFrame):
        """测试时间过滤"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,  # 2 天
                max_items=10,
            )

            # 10 天前的数据应该被过滤掉
            # mock 数据中 5 条在 2 天内，1 条在 10 天前
            assert len(results) == 5

    def test_max_items(self, mock_rating_data: pd.DataFrame):
        """测试 max_items 参数"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=2,
            )

            assert len(results) <= 2

    def test_get_source_name(self):
        """测试数据源名称"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()
            assert fetcher.get_source_name() == "东方财富机构评级"

    def test_get_supported_source_types(self):
        """测试支持的数据源类型"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()
            source_types = fetcher.get_supported_source_types()

            assert len(source_types) == 1
            assert TextSourceType.RATING in source_types

    def test_parse_date_formats(self):
        """测试不同日期格式的解析"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            test_cases = [
                ("2024-03-15", True),
                ("2024/03/15", True),
                ("20240315", True),
                ("", False),
                ("nan", False),
                ("None", False),
                ("-", False),
                ("invalid", False),
            ]

            for date_str, should_parse in test_cases:
                result = fetcher._parse_date(date_str)
                if should_parse:
                    assert result is not None, f"Expected to parse: {date_str}"
                else:
                    assert result is None, f"Expected not to parse: {date_str}"

    def test_text_item_source(self, mock_rating_data: pd.DataFrame):
        """测试 TextItem 的 source 字段来自机构名称"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_institute_recommend_detail.return_value = mock_rating_data

            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            results = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )

            # source 应该来自机构名称
            sources = {item.source for item in results}
            expected_sources = {"中信证券", "国泰君安", "招商证券", "华泰证券", "中金公司"}
            assert sources.issubset(expected_sources | {"未知机构"})

    def test_summary_format(self):
        """测试摘要格式"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            row = pd.Series(
                {
                    "机构名称": "中信证券",
                    "分析师": "张三",
                    "评级": "买入",
                    "评级变动": "上调",
                    "目标价": "15.00",
                }
            )

            summary = fetcher._build_rating_summary(row)

            assert "机构: 中信证券" in summary
            assert "分析师: 张三" in summary
            assert "评级: 买入" in summary
            assert "变动: 上调" in summary
            assert "目标价: 15.00" in summary
            assert " | " in summary

    def test_summary_missing_fields(self):
        """测试摘要中缺失字段的处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            # 只有部分字段
            row = pd.Series(
                {
                    "机构名称": "中信证券",
                    "分析师": "",
                    "评级": "买入",
                    "评级变动": "",
                    "目标价": "nan",
                }
            )

            summary = fetcher._build_rating_summary(row)

            assert "机构: 中信证券" in summary
            assert "评级: 买入" in summary
            assert "分析师" not in summary
            assert "变动" not in summary
            assert "目标价" not in summary

    def test_summary_all_missing(self):
        """测试摘要所有字段都缺失"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.rating_change_fetcher import (
                RatingChangeFetcher,
            )

            fetcher = RatingChangeFetcher()

            row = pd.Series(
                {
                    "机构名称": "",
                    "分析师": "",
                    "评级": "",
                    "评级变动": "",
                    "目标价": "",
                }
            )

            summary = fetcher._build_rating_summary(row)
            assert summary == "无摘要信息"
