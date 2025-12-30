"""
CNInfoIRMFetcher 单元测试

测试用例：
- test_fetch_and_merge_qa: 问答合并正确
- test_priority_answered_first: 有回答的排在前面
- test_sort_by_attention: 关注数高的优先
- test_non_sz_ticker_handling: 非深市股票处理
- test_fetch_texts_time_filter: 时间过滤正确
- test_fetch_texts_api_error: API 调用失败时返回空列表
- test_text_item_format: TextItem 格式正确
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_ingestion.models import TextItem
from src.data_ingestion.text.models import TextSourceType


def _create_mock_questions_data() -> pd.DataFrame:
    """创建模拟的提问数据 DataFrame"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "提问日期": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=100)).strftime("%Y-%m-%d %H:%M:%S"),  # 超过 48 小时
            ],
            "问题内容": [
                "公司的经营业绩如何？",
                "公司有什么新项目？",
                "公司的分红政策是怎样的？",
                "公司对未来发展有什么规划？",
                "这是一个过期的问题",
            ],
            "提问者": [
                "投资者A",
                "投资者B",
                "投资者C",
                "投资者D",
                "投资者E",
            ],
            "关注数": [
                100,  # 高关注
                50,
                200,  # 最高关注
                10,
                5,
            ],
        }
    )


def _create_mock_answers_data() -> pd.DataFrame:
    """创建模拟的回答数据 DataFrame"""
    now = datetime.now()
    return pd.DataFrame(
        {
            "回答日期": [
                (now - timedelta(hours=0.5)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=2.5)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=99)).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            "问题内容": [
                "公司的经营业绩如何？",
                "公司的分红政策是怎样的？",
                "这是一个过期的问题",
            ],
            "回答内容": [
                "公司业绩稳定增长，上半年营收同比增长15%。",
                "公司坚持稳定的分红政策，分红比例不低于30%。",
                "这是一个过期的回答",
            ],
            "回答者": [
                "董秘张三",
                "证代李四",
                "董秘王五",
            ],
        }
    )


@pytest.fixture
def mock_questions_data() -> pd.DataFrame:
    """创建模拟的提问数据 DataFrame"""
    return _create_mock_questions_data()


@pytest.fixture
def mock_answers_data() -> pd.DataFrame:
    """创建模拟的回答数据 DataFrame"""
    return _create_mock_answers_data()


class TestCNInfoIRMFetcher:
    """CNInfoIRMFetcher 测试类"""

    def test_fetch_and_merge_qa(
        self,
        mock_questions_data: pd.DataFrame,
        mock_answers_data: pd.DataFrame,
    ):
        """测试问答合并正确"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = mock_answers_data

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            assert len(results) > 0
            assert all(isinstance(item, TextItem) for item in results)
            assert all(item.source == "巨潮互动易" for item in results)

            # 验证有回答的问题包含回答内容
            answered = [r for r in results if "[已回复]" in r.title]
            for item in answered:
                assert "答" in item.summary
                assert "[尚未回复]" not in item.summary

    def test_priority_answered_first(
        self,
        mock_questions_data: pd.DataFrame,
        mock_answers_data: pd.DataFrame,
    ):
        """测试有回答的排在前面"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = mock_answers_data

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            # 找出有回答和无回答的索引
            answered_indices = [i for i, r in enumerate(results) if "[已回复]" in r.title]
            unanswered_indices = [i for i, r in enumerate(results) if "[待回复]" in r.title]

            # 所有有回答的应该在无回答的前面
            if answered_indices and unanswered_indices:
                assert max(answered_indices) < min(unanswered_indices)

    def test_sort_by_attention(
        self,
        mock_questions_data: pd.DataFrame,
        mock_answers_data: pd.DataFrame,
    ):
        """测试关注数高的优先"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = mock_answers_data

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            # 有回答的里面，关注数200的"分红政策"应该排在关注数100的"经营业绩"前面
            answered = [r for r in results if "[已回复]" in r.title]
            if len(answered) >= 2:
                # 第一个应该是关注数最高的（分红政策，关注数200）
                assert "分红" in answered[0].title or "分红" in answered[0].summary

    def test_non_sz_ticker_handling(self):
        """测试非深市股票处理"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            # 沪市股票
            results_sh = fetcher.fetch_texts(
                ticker="601985.SH",
                name="中国核电",
                lookback_hours=48,
                max_items=10,
            )
            assert results_sh == []

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

    def test_fetch_texts_time_filter(
        self,
        mock_questions_data: pd.DataFrame,
        mock_answers_data: pd.DataFrame,
    ):
        """测试时间过滤正确"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = mock_answers_data

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            # 验证所有返回的数据都在时间窗口内
            cutoff = datetime.now() - timedelta(hours=48, seconds=5)
            for item in results:
                assert item.published_at >= cutoff

            # 超过 48 小时的问题应被过滤掉（mock 数据中有一条 100 小时前的）
            # 在 48 小时内的问题有 4 条
            assert len(results) == 4

    def test_fetch_texts_empty(self):
        """测试无数据时返回空列表"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = pd.DataFrame()
            mock_ak.stock_irm_ans_cninfo.return_value = pd.DataFrame()

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            assert results == []

    def test_fetch_texts_api_error(self):
        """测试 API 调用失败时返回空列表"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.side_effect = Exception("API Error")
            mock_ak.stock_irm_ans_cninfo.side_effect = Exception("API Error")

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            assert results == []

    def test_fetch_texts_questions_only(
        self,
        mock_questions_data: pd.DataFrame,
    ):
        """测试只有问题数据（无回答）时返回结果"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = pd.DataFrame()

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            # 应该返回无回答的问题
            assert len(results) > 0
            for item in results:
                assert "[待回复]" in item.title
                assert "[尚未回复]" in item.summary

    def test_text_item_format(
        self,
        mock_questions_data: pd.DataFrame,
        mock_answers_data: pd.DataFrame,
    ):
        """测试 TextItem 格式正确"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = mock_answers_data

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            for item in results:
                # 检查必需字段
                assert item.source == "巨潮互动易"
                assert item.type == "news"
                assert item.title.startswith("[已回复]") or item.title.startswith("[待回复]")
                assert item.summary.startswith("问:")
                assert item.published_at is not None
                assert item.url is None  # 巨潮互动易无直接链接

    def test_title_truncation(self):
        """测试长问题标题截断"""
        long_question = "这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的问题"
        now = datetime.now()
        questions_df = pd.DataFrame(
            {
                "提问日期": [now.strftime("%Y-%m-%d %H:%M:%S")],
                "问题内容": [long_question],
                "提问者": ["投资者A"],
                "关注数": [100],
            }
        )

        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = questions_df
            mock_ak.stock_irm_ans_cninfo.return_value = pd.DataFrame()

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            assert len(results) == 1
            # 标题应该被截断并添加 "..."
            assert results[0].title.endswith("...")
            # 标题长度应该在合理范围内 ([待回复] + 40字 + ...)
            assert len(results[0].title) <= 50

    def test_responder_in_summary(
        self,
        mock_questions_data: pd.DataFrame,
        mock_answers_data: pd.DataFrame,
    ):
        """测试回答者信息包含在摘要中"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = mock_answers_data

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            # 有回答的应该包含回答者信息
            answered = [r for r in results if "[已回复]" in r.title]
            for item in answered:
                # 回答者应该出现在摘要中（括号内）
                assert "董秘" in item.summary or "证代" in item.summary

    def test_get_source_name(self):
        """测试数据源名称"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()
            assert fetcher.get_source_name() == "巨潮互动易"

    def test_supports_market(self):
        """测试市场支持判断"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            # 深市股票
            assert fetcher.supports_market("000001.SZ") is True
            assert fetcher.supports_market("000001.sz") is True  # 小写也支持

            # 非深市股票
            assert fetcher.supports_market("601985.SH") is False
            assert fetcher.supports_market("0700.HK") is False
            assert fetcher.supports_market("AAPL") is False

    def test_get_supported_source_types(self):
        """测试支持的数据源类型"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()
            source_types = fetcher.get_supported_source_types()

            assert len(source_types) == 1
            assert TextSourceType.IRM in source_types

    def test_max_items(
        self,
        mock_questions_data: pd.DataFrame,
        mock_answers_data: pd.DataFrame,
    ):
        """测试 max_items 参数生效"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = mock_questions_data
            mock_ak.stock_irm_ans_cninfo.return_value = mock_answers_data

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=2,
            )

            assert len(results) <= 2

    def test_parse_datetime_formats(self):
        """测试不同日期格式的解析"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

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

    def test_extract_symbol(self):
        """测试 ticker 代码提取"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            assert fetcher.extract_symbol("000001.SZ") == "000001"
            assert fetcher.extract_symbol("601985.SH") == "601985"
            assert fetcher.extract_symbol("AAPL") == "AAPL"

    def test_none_dataframe_returns_empty(self):
        """测试返回 None 时返回空列表"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            mock_ak = sys.modules["akshare"]
            mock_ak.stock_irm_cninfo.return_value = None
            mock_ak.stock_irm_ans_cninfo.return_value = None

            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            results = fetcher.fetch_texts(
                ticker="000001.SZ",
                name="平安银行",
                lookback_hours=48,
                max_items=10,
            )

            assert results == []

    def test_build_qa_summary(self):
        """测试问答摘要构建"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            # 有回答有回答者
            summary1 = fetcher._build_qa_summary(
                question="公司业绩如何？",
                answer="业绩良好",
                responder="董秘张三",
            )
            assert summary1 == "问: 公司业绩如何？\n答(董秘张三): 业绩良好"

            # 有回答无回答者
            summary2 = fetcher._build_qa_summary(
                question="公司业绩如何？",
                answer="业绩良好",
                responder=None,
            )
            assert summary2 == "问: 公司业绩如何？\n答: 业绩良好"

            # 无回答
            summary3 = fetcher._build_qa_summary(
                question="公司业绩如何？",
                answer=None,
                responder=None,
            )
            assert summary3 == "问: 公司业绩如何？\n[尚未回复]"

    def test_merge_qa_matching(self):
        """测试问答匹配逻辑"""
        with patch.dict(sys.modules, {"akshare": MagicMock()}):
            from src.data_ingestion.text.a_share.cninfo_irm_fetcher import CNInfoIRMFetcher
            fetcher = CNInfoIRMFetcher()

            now = datetime.now()
            questions_df = pd.DataFrame(
                {
                    "提问日期": [now.strftime("%Y-%m-%d %H:%M:%S")] * 3,
                    "问题内容": ["问题A", "问题B", "问题C"],
                    "提问者": ["投资者A", "投资者B", "投资者C"],
                    "关注数": [10, 20, 30],
                }
            )

            answers_df = pd.DataFrame(
                {
                    "回答日期": [now.strftime("%Y-%m-%d %H:%M:%S")] * 2,
                    "问题内容": ["问题A", "问题C"],  # 只回答了 A 和 C
                    "回答内容": ["回答A", "回答C"],
                    "回答者": ["董秘", "证代"],
                }
            )

            merged = fetcher._merge_qa(questions_df, answers_df)

            assert len(merged) == 3

            # 检查匹配结果
            qa_a = next(qa for qa in merged if qa["question"] == "问题A")
            assert qa_a["has_answer"] is True
            assert qa_a["answer"] == "回答A"
            assert qa_a["responder"] == "董秘"

            qa_b = next(qa for qa in merged if qa["question"] == "问题B")
            assert qa_b["has_answer"] is False
            assert qa_b["answer"] is None

            qa_c = next(qa for qa in merged if qa["question"] == "问题C")
            assert qa_c["has_answer"] is True
            assert qa_c["answer"] == "回答C"
