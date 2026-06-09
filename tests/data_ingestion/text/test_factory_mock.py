"""
TextProviderFactory use_mock 路由测试

验证 use_mock=True 时工厂统一返回 MockTextProvider（覆盖 A 股 / 港股 / 美股），
且不影响默认（非 mock）选择逻辑。对应 P1 Step 1：打通离线 mock 文本路径。
"""
import pytest

from src.data_ingestion.models import TextItem
from src.data_ingestion.text import MockTextProvider, TextProviderFactory


@pytest.fixture(autouse=True)
def _reset_factory():
    """每个用例前后重置工厂单例缓存，避免跨用例污染"""
    TextProviderFactory.reset()
    yield
    TextProviderFactory.reset()


class TestFactoryUseMock:
    """use_mock 路由测试类"""

    @pytest.mark.parametrize("ticker", ["601985.SH", "000001.SZ", "0700.HK", "AAPL"])
    def test_get_provider_returns_mock_for_all_markets(self, ticker):
        """use_mock=True 时所有市场都返回 MockTextProvider"""
        provider = TextProviderFactory.get_provider(ticker, use_mock=True)
        assert isinstance(provider, MockTextProvider)

    def test_mock_provider_is_singleton(self):
        """Mock Provider 走单例缓存"""
        p1 = TextProviderFactory.get_provider("601985.SH", use_mock=True)
        p2 = TextProviderFactory.get_provider("AAPL", use_mock=True)
        assert p1 is p2

    def test_fetch_texts_use_mock_returns_items(self):
        """fetch_texts(use_mock=True) 返回 Mock 文本"""
        texts = TextProviderFactory.fetch_texts(
            ticker="601985.SH", name="中国核电", use_mock=True
        )
        assert len(texts) > 0
        assert all(isinstance(t, TextItem) for t in texts)
        # Mock 数据的 URL 固定指向 mock.example.com，借此确认走的是 Mock 路径
        assert all("mock.example.com" in (t.url or "") for t in texts)

    def test_default_path_is_not_mock_for_a_share(self):
        """默认（use_mock=False）A 股不应返回 MockTextProvider"""
        provider = TextProviderFactory.get_provider("601985.SH")
        assert not isinstance(provider, MockTextProvider)

    def test_reset_clears_mock_provider(self):
        """reset() 清空 Mock Provider 单例缓存"""
        p1 = TextProviderFactory.get_provider("601985.SH", use_mock=True)
        TextProviderFactory.reset()
        p2 = TextProviderFactory.get_provider("601985.SH", use_mock=True)
        assert p1 is not p2
