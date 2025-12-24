"""
use_mock 配置测试

测试用例：
- test_use_mock_default_false: 测试 use_mock 默认值为 False
- test_use_mock_can_be_set_true: 测试 use_mock 可以设置为 True
"""
import pytest

from src.config import load_config_from_dict
from src.config.models import CrawlerConfig


class TestUseMockConfig:
    """use_mock 配置测试类"""

    def test_use_mock_default_false(self):
        """测试 use_mock 默认值为 False"""
        config = load_config_from_dict({"targets": []})
        assert config.data_sources.crawler.use_mock is False

    def test_use_mock_can_be_set_true(self):
        """测试 use_mock 可以设置为 True"""
        config = load_config_from_dict({
            "targets": [],
            "data_sources": {
                "crawler": {
                    "use_mock": True
                }
            }
        })
        assert config.data_sources.crawler.use_mock is True

    def test_use_mock_can_be_set_false_explicitly(self):
        """测试 use_mock 可以显式设置为 False"""
        config = load_config_from_dict({
            "targets": [],
            "data_sources": {
                "crawler": {
                    "use_mock": False
                }
            }
        })
        assert config.data_sources.crawler.use_mock is False

    def test_crawler_config_with_use_mock(self):
        """测试 CrawlerConfig 包含 use_mock 字段"""
        crawler_config = CrawlerConfig()
        assert hasattr(crawler_config, 'use_mock')
        assert crawler_config.use_mock is False

    def test_crawler_config_use_mock_true(self):
        """测试 CrawlerConfig use_mock 设置为 True"""
        crawler_config = CrawlerConfig(use_mock=True)
        assert crawler_config.use_mock is True

    def test_full_config_with_mock_and_other_crawler_settings(self):
        """测试完整配置中 use_mock 与其他爬虫配置共存"""
        config = load_config_from_dict({
            "targets": [],
            "data_sources": {
                "crawler": {
                    "use_mock": True,
                    "use_llm_for_sources": False,
                    "lookback_hours": 24,
                    "max_items_per_ticker": 5
                }
            }
        })
        assert config.data_sources.crawler.use_mock is True
        assert config.data_sources.crawler.use_llm_for_sources is False
        assert config.data_sources.crawler.lookback_hours == 24
        assert config.data_sources.crawler.max_items_per_ticker == 5
