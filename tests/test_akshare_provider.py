"""
AkShare 文本数据提供者单元测试
"""
import sys
from unittest.mock import MagicMock

# Mock akshare module before importing any modules that depend on it
# This allows tests to run without the actual akshare package installed
mock_akshare = MagicMock()
sys.modules["akshare"] = mock_akshare

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import pandas as pd

from src.data_ingestion.text.akshare_provider import AkShareTextProvider
from src.data_ingestion.text.akshare.news_fetcher import AkShareNewsFetcher
from src.data_ingestion.text.akshare.research_fetcher import AkShareResearchFetcher
from src.data_ingestion.text.akshare.pdf_extractor import PDFExtractor
from src.data_ingestion.models import TextItem


class TestAkShareNewsFetcher:
    """测试新闻获取器"""

    @pytest.fixture
    def mock_news_df(self):
        """模拟 AkShare 返回的新闻数据"""
        now = datetime.now()
        return pd.DataFrame({
            "新闻标题": ["标题1", "标题2", "标题3"],
            "新闻内容": ["内容1", "内容2", "内容3"],
            "发布时间": [
                (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S"),
            ],
            "文章来源": ["东方财富", "证券时报", "新浪财经"],
            "新闻链接": ["http://a", "http://b", "http://c"],
        })

    def test_fetch_returns_text_items(self, mock_news_df):
        """测试返回正确的 TextItem 列表"""
        with patch("akshare.stock_news_em", return_value=mock_news_df):
            fetcher = AkShareNewsFetcher()
            results = fetcher.fetch("601985", lookback_hours=48)

            assert len(results) == 2  # 72小时前的被过滤
            assert all(isinstance(item, TextItem) for item in results)
            assert all(item.type == "news" for item in results)

    def test_lookback_filter(self, mock_news_df):
        """测试时间过滤"""
        with patch("akshare.stock_news_em", return_value=mock_news_df):
            fetcher = AkShareNewsFetcher()
            results = fetcher.fetch("601985", lookback_hours=12)

            assert len(results) == 1  # 只有 1 小时前的

    def test_max_items_limit(self, mock_news_df):
        """测试最大返回数量限制"""
        with patch("akshare.stock_news_em", return_value=mock_news_df):
            fetcher = AkShareNewsFetcher()
            results = fetcher.fetch("601985", lookback_hours=48, max_items=1)

            assert len(results) == 1

    def test_empty_dataframe(self):
        """测试空数据返回空列表"""
        with patch("akshare.stock_news_em", return_value=pd.DataFrame()):
            fetcher = AkShareNewsFetcher()
            results = fetcher.fetch("601985")

            assert results == []

    def test_api_error_returns_empty_list(self):
        """测试 API 错误返回空列表"""
        with patch("akshare.stock_news_em", side_effect=Exception("API Error")):
            fetcher = AkShareNewsFetcher()
            results = fetcher.fetch("601985")

            assert results == []

    def test_parse_datetime_formats(self):
        """测试日期格式解析"""
        fetcher = AkShareNewsFetcher()

        # 完整格式
        result = fetcher._parse_datetime("2024-01-15 10:30:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0)

        # 无秒
        result = fetcher._parse_datetime("2024-01-15 10:30")
        assert result == datetime(2024, 1, 15, 10, 30)

        # 只有日期
        result = fetcher._parse_datetime("2024-01-15")
        assert result == datetime(2024, 1, 15)

        # 无效格式
        result = fetcher._parse_datetime("invalid")
        assert result is None

        # 空字符串
        result = fetcher._parse_datetime("")
        assert result is None

    def test_truncate_content(self):
        """测试内容截断"""
        fetcher = AkShareNewsFetcher()

        # 短内容不截断
        short = "短内容"
        assert fetcher._truncate_content(short, 100) == short

        # 长内容截断
        long = "a" * 200
        result = fetcher._truncate_content(long, 50)
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")


class TestAkShareResearchFetcher:
    """测试研报获取器"""

    @pytest.fixture
    def mock_research_df(self):
        """模拟 AkShare 返回的研报数据"""
        today = datetime.now().date()
        return pd.DataFrame({
            "报告名称": ["深度报告：核电迎来机遇期", "点评：业绩符合预期"],
            "机构": ["中信证券", "华泰证券"],
            "东财评级": ["买入", "增持"],
            "日期": [
                today.strftime("%Y-%m-%d"),
                (today - timedelta(days=3)).strftime("%Y-%m-%d"),
            ],
            "报告PDF链接": [
                "https://pdf.dfcfw.com/xxx.pdf",
                "https://pdf.dfcfw.com/yyy.pdf",
            ],
            "2025-盈利预测-收益": [0.45, 0.42],
            "2025-盈利预测-市盈率": [19.7, 21.2],
            "行业": ["电力", "电力"],
        })

    def test_fetch_without_pdf(self, mock_research_df):
        """测试不解析 PDF 时的获取"""
        with patch("akshare.stock_research_report_em", return_value=mock_research_df):
            fetcher = AkShareResearchFetcher(extract_pdf=False)
            results = fetcher.fetch("601985", lookback_hours=48)

            assert len(results) == 1  # 3天前的被过滤
            assert results[0].type == "research"
            assert "买入" in results[0].summary or "评级" in results[0].summary

    def test_fetch_with_longer_lookback(self, mock_research_df):
        """测试更长回溯时间"""
        with patch("akshare.stock_research_report_em", return_value=mock_research_df):
            fetcher = AkShareResearchFetcher(extract_pdf=False)
            results = fetcher.fetch("601985", lookback_hours=168)  # 7 days

            assert len(results) == 2

    def test_empty_dataframe(self):
        """测试空数据返回空列表"""
        with patch("akshare.stock_research_report_em", return_value=pd.DataFrame()):
            fetcher = AkShareResearchFetcher(extract_pdf=False)
            results = fetcher.fetch("601985")

            assert results == []

    def test_api_error_returns_empty_list(self):
        """测试 API 错误返回空列表"""
        with patch("akshare.stock_research_report_em", side_effect=Exception("API Error")):
            fetcher = AkShareResearchFetcher(extract_pdf=False)
            results = fetcher.fetch("601985")

            assert results == []

    def test_build_summary_without_pdf(self, mock_research_df):
        """测试摘要构建（不含 PDF）"""
        fetcher = AkShareResearchFetcher(extract_pdf=False)
        row = mock_research_df.iloc[0]

        summary = fetcher._build_summary(row, None)

        assert "评级: 买入" in summary
        assert "2025E" in summary or "电力" in summary

    def test_parse_date_formats(self):
        """测试日期格式解析"""
        fetcher = AkShareResearchFetcher(extract_pdf=False)

        # 标准格式
        result = fetcher._parse_date("2024-01-15")
        assert result == datetime(2024, 1, 15).date()

        # 斜杠格式
        result = fetcher._parse_date("2024/01/15")
        assert result == datetime(2024, 1, 15).date()

        # 紧凑格式
        result = fetcher._parse_date("20240115")
        assert result == datetime(2024, 1, 15).date()

        # 无效格式
        result = fetcher._parse_date("invalid")
        assert result is None


class TestPDFExtractor:
    """测试 PDF 提取器"""

    def test_init_without_llm(self):
        """测试不使用 LLM 初始化"""
        extractor = PDFExtractor(llm_client=None, use_llm=False)
        assert extractor._use_llm is False

    def test_init_with_llm(self):
        """测试使用 LLM 初始化"""
        mock_llm = Mock()
        extractor = PDFExtractor(llm_client=mock_llm, use_llm=True)
        assert extractor._use_llm is True

    def test_clean_text(self):
        """测试文本清理"""
        extractor = PDFExtractor()

        # 多余空白
        result = extractor._clean_text("  多  余   空白  ")
        assert result == "多 余 空白"

        # 页码
        result = extractor._clean_text("内容 第 1 页 结尾")
        assert "第" not in result or "页" not in result

        # 特殊字符
        result = extractor._clean_text("■内容●要点◆")
        assert "■" not in result
        assert "●" not in result
        assert "◆" not in result

    def test_extract_key_sections(self):
        """测试关键段落提取"""
        extractor = PDFExtractor()

        raw_text = """
        投资要点：本公司是核电行业龙头，受益于AI算力需求增长带来的电力消耗提升。

        风险提示：政策变化风险、核电安全风险、项目进度风险。

        其他内容不重要。
        """

        result = extractor._extract_key_sections(raw_text)

        # 应该提取到关键段落
        assert "投资要点" in result or "风险提示" in result

    def test_download_pdf_timeout(self):
        """测试 PDF 下载超时"""
        import httpx

        extractor = PDFExtractor(timeout=0.001)

        with patch.object(
            httpx.Client, "get", side_effect=httpx.TimeoutException("timeout")
        ):
            result = extractor._download_pdf("https://example.com/test.pdf")
            assert result is None

    def test_download_pdf_error(self):
        """测试 PDF 下载错误"""
        extractor = PDFExtractor()

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = Mock(
                side_effect=Exception("Connection error")
            )
            result = extractor._download_pdf("https://example.com/test.pdf")
            assert result is None


class TestAkShareTextProvider:
    """测试主入口"""

    def test_is_a_share(self):
        """测试 A 股判断"""
        assert AkShareTextProvider.is_a_share("601985.SH") is True
        assert AkShareTextProvider.is_a_share("000001.SZ") is True
        assert AkShareTextProvider.is_a_share("0700.HK") is False
        assert AkShareTextProvider.is_a_share("AAPL") is False

    def test_extract_symbol(self):
        """测试代码提取"""
        provider = AkShareTextProvider(llm_client=None, extract_pdf=False)
        assert provider._extract_symbol("601985.SH") == "601985"
        assert provider._extract_symbol("000001.SZ") == "000001"
        assert provider._extract_symbol("0700.HK") is None

    def test_extract_symbol_pure_code(self):
        """测试纯数字代码提取"""
        provider = AkShareTextProvider(llm_client=None, extract_pdf=False)
        assert provider._extract_symbol("601985") == "601985"
        assert provider._extract_symbol("000001") == "000001"
        assert provider._extract_symbol("12345") is None  # 非 6 位

    def test_get_source_name(self):
        """测试数据源名称"""
        provider = AkShareTextProvider(llm_client=None, extract_pdf=False)
        assert provider.get_source_name() == "akshare"

    def test_non_a_share_returns_empty(self):
        """测试非 A 股返回空列表"""
        provider = AkShareTextProvider(llm_client=None, extract_pdf=False)
        results = provider.fetch_texts("0700.HK", "腾讯控股")
        assert results == []

    @patch.object(AkShareNewsFetcher, "fetch")
    @patch.object(AkShareResearchFetcher, "fetch")
    def test_fetch_texts_combines_sources(self, mock_research, mock_news):
        """测试合并新闻和研报"""
        now = datetime.now()

        mock_news.return_value = [
            TextItem(
                source="东方财富",
                type="news",
                title="新闻标题",
                summary="新闻摘要",
                published_at=now - timedelta(hours=1),
            )
        ]
        mock_research.return_value = [
            TextItem(
                source="中信证券",
                type="research",
                title="研报标题",
                summary="研报摘要",
                published_at=now - timedelta(hours=2),
            )
        ]

        provider = AkShareTextProvider(llm_client=None, extract_pdf=False)
        results = provider.fetch_texts("601985.SH", "中国核电")

        assert len(results) == 2
        # 应该按时间排序（最新的在前）
        assert results[0].type == "news"
        assert results[1].type == "research"

    @patch.object(AkShareNewsFetcher, "fetch")
    @patch.object(AkShareResearchFetcher, "fetch")
    def test_fetch_texts_respects_max_items(self, mock_research, mock_news):
        """测试最大返回数量限制"""
        now = datetime.now()

        mock_news.return_value = [
            TextItem(
                source="东方财富",
                type="news",
                title=f"新闻{i}",
                summary="摘要",
                published_at=now - timedelta(hours=i),
            )
            for i in range(5)
        ]
        mock_research.return_value = [
            TextItem(
                source="中信证券",
                type="research",
                title=f"研报{i}",
                summary="摘要",
                published_at=now - timedelta(hours=i + 10),
            )
            for i in range(5)
        ]

        provider = AkShareTextProvider(llm_client=None, extract_pdf=False)
        results = provider.fetch_texts("601985.SH", "中国核电", max_items=5)

        assert len(results) == 5


@pytest.mark.integration
class TestAkShareIntegration:
    """集成测试（需要网络）"""

    def test_real_news_fetch(self):
        """测试真实新闻获取"""
        fetcher = AkShareNewsFetcher()
        results = fetcher.fetch("601985", lookback_hours=168, max_items=5)

        # 可能没有最近的新闻，但不应报错
        assert isinstance(results, list)
        for item in results:
            assert item.type == "news"
            assert item.title

    def test_real_research_fetch(self):
        """测试真实研报获取（不含 PDF 解析）"""
        fetcher = AkShareResearchFetcher(extract_pdf=False)
        results = fetcher.fetch("601985", lookback_hours=720, max_items=3)

        assert isinstance(results, list)
        for item in results:
            assert item.type == "research"
            assert item.url  # 应有 PDF 链接

    def test_full_provider_integration(self):
        """测试完整 Provider 集成"""
        provider = AkShareTextProvider(llm_client=None, extract_pdf=False)
        results = provider.fetch_texts(
            "601985.SH",
            "中国核电",
            lookback_hours=720,  # 30 days
            max_items=10,
        )

        assert isinstance(results, list)
        # 可能没有最近的数据，但不应报错
        for item in results:
            assert item.type in ("news", "research")
            assert item.title
            assert item.published_at
