"""
SSEInteractiveFetcher 单元测试

测试用例：
- test_fetch_texts_success: 正常获取数据
- test_fetch_texts_empty: 无数据时返回空列表
- test_fetch_texts_time_filter: 时间过滤正确
- test_fetch_texts_market_check: 非沪市股票应返回空列表
- test_fetch_texts_api_error: API 调用失败时返回空列表
- test_fetch_texts_answered_priority: 有回复的问答优先
- test_fetch_texts_sorted_by_time: 结果按时间倒序排列
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_ingestion.models import TextItem
from src.data_ingestion.text.a_share.sse_interactive_fetcher import SSEInteractiveFetcher
from src.data_ingestion.text.models import TextSourceType

# akshare 的 MagicMock 占位符。SSEInteractiveFetcher 在方法内部惰性 `import akshare`，
# 因此导入 fetcher 时并不会真正加载 akshare，无需在 import 时注入。
# 真正的注入由下方的 autouse fixture 完成：每个测试都会重建一个全新的 mock，
# 并通过 patch.dict 仅在该测试期间放入 sys.modules（结束后自动还原），
# 避免在 import 时篡改 sys.modules 导致跨测试/跨文件泄漏。
mock_akshare = MagicMock()


@pytest.fixture(autouse=True)
def _mock_akshare_module():
    """为每个测试注入独立的 akshare mock，并在结束后还原 sys.modules。"""
    global mock_akshare
    mock_akshare = MagicMock()
    with patch.dict(sys.modules, {"akshare": mock_akshare}):
        yield mock_akshare


@pytest.fixture
def fetcher() -> SSEInteractiveFetcher:
    """创建 SSEInteractiveFetcher 实例"""
    return SSEInteractiveFetcher()


@pytest.fixture
def mock_qa_data() -> pd.DataFrame:
    """创建模拟的问答数据 DataFrame"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "提问时间": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=100)).strftime("%Y-%m-%d %H:%M:%S"),  # 超过 48 小时
            ],
            "问题": [
                "公司的核电机组核准进展如何？",
                "公司对 AI 算力用电需求如何看待？",
                "公司的分红政策是怎样的？",
                "这是一个过期的问题",
            ],
            "回复时间": [
                (now - timedelta(hours=0.5)).strftime("%Y-%m-%d %H:%M:%S"),
                "",  # 无回复
                (now - timedelta(hours=2.5)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=99)).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            "答复": [
                "公司目前有多个核电机组正在建设中，核准进展顺利。",
                "",  # 无回复
                "公司坚持稳定的分红政策，连续多年保持较高分红比例。",
                "这是一个过期的回答",
            ],
        }
    )


class TestSSEInteractiveFetcher:
    """SSEInteractiveFetcher 测试类"""

    def test_fetch_texts_success(
        self, fetcher: SSEInteractiveFetcher, mock_qa_data: pd.DataFrame
    ):
        """测试正常获取数据"""
        mock_akshare.stock_sns_sseinfo.return_value = mock_qa_data

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        assert len(results) > 0
        assert all(isinstance(item, TextItem) for item in results)
        assert all(item.source == "上证e互动" for item in results)
        assert all(item.type == "news" for item in results)

    def test_fetch_texts_empty(self, fetcher: SSEInteractiveFetcher):
        """测试无数据时返回空列表"""
        mock_akshare.stock_sns_sseinfo.return_value = pd.DataFrame()

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        assert results == []

    def test_fetch_texts_time_filter(
        self, fetcher: SSEInteractiveFetcher, mock_qa_data: pd.DataFrame
    ):
        """测试时间过滤正确"""
        mock_akshare.stock_sns_sseinfo.return_value = mock_qa_data

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        # 验证所有返回的数据都在时间窗口内
        cutoff = datetime.now() - timedelta(hours=48, seconds=5)
        for item in results:
            assert item.published_at >= cutoff

        # 超过 48 小时的问题应被过滤掉（mock 数据中有一条 100 小时前的）
        assert len(results) == 3  # 只有 3 条在 48 小时内

    def test_fetch_texts_market_check(self, fetcher: SSEInteractiveFetcher):
        """测试非沪市股票应返回空列表"""
        # 深市股票
        results_sz = fetcher.fetch_texts(
            ticker="000001.SZ",
            name="平安银行",
            lookback_hours=48,
            max_items=10,
        )
        assert results_sz == []

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

    def test_fetch_texts_api_error(self, fetcher: SSEInteractiveFetcher):
        """测试 API 调用失败时返回空列表"""
        mock_akshare.stock_sns_sseinfo.side_effect = Exception("API Error")

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        assert results == []

        # Reset side_effect for other tests
        mock_akshare.stock_sns_sseinfo.side_effect = None

    def test_fetch_texts_answered_priority(
        self, fetcher: SSEInteractiveFetcher, mock_qa_data: pd.DataFrame
    ):
        """测试有回复的问答优先返回"""
        mock_akshare.stock_sns_sseinfo.return_value = mock_qa_data

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        # 前两条应该是有回复的
        assert "答:" in results[0].summary and "暂无回复" not in results[0].summary
        assert "答:" in results[1].summary and "暂无回复" not in results[1].summary

        # 最后一条是无回复的
        assert "暂无回复" in results[-1].summary

    def test_fetch_texts_sorted_by_time(
        self, fetcher: SSEInteractiveFetcher, mock_qa_data: pd.DataFrame
    ):
        """测试结果按时间倒序排列（在同类别内）"""
        mock_akshare.stock_sns_sseinfo.return_value = mock_qa_data

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        # 有回复的应该按时间倒序（第一条的回复时间最新）
        answered = [r for r in results if "暂无回复" not in r.summary]
        for i in range(len(answered) - 1):
            assert answered[i].published_at >= answered[i + 1].published_at

    def test_fetch_texts_max_items(
        self, fetcher: SSEInteractiveFetcher, mock_qa_data: pd.DataFrame
    ):
        """测试 max_items 参数生效"""
        mock_akshare.stock_sns_sseinfo.return_value = mock_qa_data

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=2,
        )

        assert len(results) <= 2

    def test_get_source_name(self, fetcher: SSEInteractiveFetcher):
        """测试数据源名称"""
        assert fetcher.get_source_name() == "上证e互动"

    def test_supports_market(self, fetcher: SSEInteractiveFetcher):
        """测试市场支持判断"""
        # 沪市股票
        assert fetcher.supports_market("601985.SH") is True
        assert fetcher.supports_market("600150.sh") is True  # 小写也支持

        # 非沪市股票
        assert fetcher.supports_market("000001.SZ") is False
        assert fetcher.supports_market("0700.HK") is False
        assert fetcher.supports_market("AAPL") is False

    def test_get_supported_source_types(self, fetcher: SSEInteractiveFetcher):
        """测试支持的数据源类型"""
        source_types = fetcher.get_supported_source_types()

        assert len(source_types) == 1
        assert TextSourceType.IRM in source_types

    def test_text_item_format(
        self, fetcher: SSEInteractiveFetcher, mock_qa_data: pd.DataFrame
    ):
        """测试 TextItem 格式正确"""
        mock_akshare.stock_sns_sseinfo.return_value = mock_qa_data

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        for item in results:
            # 检查必需字段
            assert item.source == "上证e互动"
            assert item.type == "news"
            assert item.title.startswith("[投资者提问]")
            assert item.summary.startswith("问:")
            assert "答:" in item.summary
            assert item.published_at is not None
            assert item.url is None  # e互动无直接链接

    def test_title_truncation(self, fetcher: SSEInteractiveFetcher):
        """测试长问题标题截断"""
        long_question = "这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的问题，明确超过了五十个字符的长度限制"
        now = datetime.now()
        df = pd.DataFrame(
            {
                "提问时间": [now.strftime("%Y-%m-%d %H:%M:%S")],
                "问题": [long_question],
                "回复时间": [""],
                "答复": [""],
            }
        )

        mock_akshare.stock_sns_sseinfo.return_value = df

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        assert len(results) == 1
        # 标题应该被截断并添加 "..."
        assert results[0].title.endswith("...")
        assert len(results[0].title) < len(f"[投资者提问] {long_question}")

    def test_parse_datetime_formats(self, fetcher: SSEInteractiveFetcher):
        """测试不同日期格式的解析"""
        test_cases = [
            ("2024-03-15 18:30:00", True),
            ("2024-03-15 18:30", True),
            ("2024-03-15", True),
            ("2024/03/15 18:30:00", True),
            ("2024/03/15", True),
            ("", False),
            ("nan", False),
            ("None", False),
            ("-", False),
            ("invalid", False),
        ]

        for date_str, should_parse in test_cases:
            result = fetcher._parse_datetime(date_str)
            if should_parse:
                assert result is not None, f"Expected to parse: {date_str}"
            else:
                assert result is None, f"Expected not to parse: {date_str}"

    def test_has_valid_answer(self, fetcher: SSEInteractiveFetcher):
        """测试回答有效性判断"""
        assert fetcher._has_valid_answer("有效回答") is True
        assert fetcher._has_valid_answer("") is False
        assert fetcher._has_valid_answer("nan") is False
        assert fetcher._has_valid_answer("-") is False
        assert fetcher._has_valid_answer("暂无回复") is False
        assert fetcher._has_valid_answer("None") is False

    def test_extract_symbol(self, fetcher: SSEInteractiveFetcher):
        """测试 ticker 代码提取"""
        assert fetcher.extract_symbol("601985.SH") == "601985"
        assert fetcher.extract_symbol("000001.SZ") == "000001"
        assert fetcher.extract_symbol("AAPL") == "AAPL"

    def test_none_dataframe_returns_empty(self, fetcher: SSEInteractiveFetcher):
        """测试返回 None 时返回空列表"""
        mock_akshare.stock_sns_sseinfo.return_value = None

        results = fetcher.fetch_texts(
            ticker="601985.SH",
            name="中国核电",
            lookback_hours=48,
            max_items=10,
        )

        assert results == []
