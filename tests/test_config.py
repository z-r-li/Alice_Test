"""
配置加载测试

测试用例：
- test_load_config: 加载示例配置
- test_env_var_injection: 环境变量 getter 不写回配置对象
- test_config_validation: 配置验证
- test_config_manager: ConfigManager 功能测试
"""
import os
from pathlib import Path

import pytest

from src.config.manager import (
    ConfigError,
    ConfigManager,
    get_config,
    load_config,
    load_config_from_dict,
    reset_global_config,
    set_global_config,
)
from src.config.models import (
    AppConfig,
    GapThresholdConfig,
    LLMConfig,
    TargetConfig,
)


class TestLoadConfig:
    """配置加载测试类"""

    def test_load_config_from_file(self, temp_config_path: Path, sample_config_yaml_content: str):
        """测试从文件加载配置"""
        # 写入测试配置文件
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        # 加载配置
        config = load_config(temp_config_path)

        # 验证配置
        assert config.llm_api.provider == "deepseek"
        assert config.llm_api.model == "deepseek-v4-flash"
        assert len(config.targets) == 1
        assert config.targets[0].ticker == "601985.SH"

    def test_load_config_file_not_found(self, temp_dir: Path):
        """测试配置文件不存在时抛出错误"""
        non_existent_path = temp_dir / "non_existent.yaml"

        with pytest.raises(ConfigError) as exc_info:
            load_config(non_existent_path)

        assert "配置文件不存在" in str(exc_info.value)

    def test_load_config_invalid_yaml(self, temp_config_path: Path):
        """测试无效 YAML 格式"""
        invalid_yaml = """
        llm_api:
          provider: "deepseek"
          invalid: yaml: content
        """
        temp_config_path.write_text(invalid_yaml, encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            load_config(temp_config_path)

        assert "YAML 解析错误" in str(exc_info.value)

    def test_config_example_parses(self):
        """M7：仓库示例配置必须能被严格 schema 真实解析。"""
        config = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")

        assert config.llm_api.model == "deepseek-v4-flash"
        assert len(config.targets) >= 1


class TestLoadConfigFromDict:
    """从字典加载配置测试类"""

    def test_load_config_from_dict_success(self, sample_config_dict: dict):
        """测试从字典加载配置成功"""
        config = load_config_from_dict(sample_config_dict)

        assert config.llm_api.api_key == "test-key"
        assert len(config.targets) == 1
        assert config.targets[0].name == "中国核电"

    def test_load_config_from_dict_minimal(self):
        """测试最小配置字典"""
        minimal_config = {
            "targets": [
                {
                    "ticker": "AAPL",
                    "name": "Apple",
                    "thesis": "科技巨头长期增长",
                }
            ]
        }
        config = load_config_from_dict(minimal_config)

        assert len(config.targets) == 1
        assert config.targets[0].ticker == "AAPL"
        # 默认值应该被填充
        assert config.llm_api.provider == "deepseek"
        assert config.llm_api.model == "deepseek-v4-flash"

    def test_load_config_from_dict_validation_error(self):
        """测试配置验证失败"""
        invalid_config = {
            "targets": [
                {
                    "ticker": "",  # 空 ticker 无效
                    "name": "Test",
                    "thesis": "Test",
                }
            ]
        }
        with pytest.raises(ConfigError) as exc_info:
            load_config_from_dict(invalid_config)

        assert "配置验证失败" in str(exc_info.value)

    def test_load_config_from_dict_rejects_unknown_top_level_key(self):
        with pytest.raises(ConfigError) as exc_info:
            load_config_from_dict({
                "unknown_section": {},
                "targets": [{"ticker": "AAPL", "name": "Apple", "thesis": "测试"}],
            })

        assert "extra_forbidden" in str(exc_info.value)

    def test_load_config_from_dict_rejects_unknown_nested_key(self):
        with pytest.raises(ConfigError) as exc_info:
            load_config_from_dict({
                "targets": [{"ticker": "AAPL", "name": "Apple", "thesis": "测试"}],
                "gap_thresholds": {"opportunity": 5.0},
            })

        assert "extra_forbidden" in str(exc_info.value)


class TestEnvVarInjection:
    """环境变量 getter 测试类"""

    def test_deepseek_api_key_env_getter_without_config_injection(
        self,
        temp_config_path: Path,
        env_with_api_key,
    ):
        """DEEPSEEK_API_KEY 运行期可读，但不写回 AppConfig。"""
        # 配置文件中不设置 api_key
        config_content = """
llm_api:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  temperature: 0

targets:
  - ticker: "TEST.SH"
    name: "测试"
    thesis: "测试信念"
"""
        temp_config_path.write_text(config_content, encoding="utf-8")

        config = load_config(temp_config_path)

        assert config.llm_api.api_key == ""
        assert config.llm_api.get_api_key() == "env-test-api-key"

    def test_tushare_token_env_getter_without_config_injection(
        self,
        temp_config_path: Path,
        env_with_tushare_token,
    ):
        """TUSHARE_TOKEN 运行期可读，但不写回 AppConfig。"""
        config_content = """
llm_api:
  provider: "deepseek"

data_sources:
  a_shares:
    provider: "tushare"

targets:
  - ticker: "TEST.SH"
    name: "测试"
    thesis: "测试信念"
"""
        temp_config_path.write_text(config_content, encoding="utf-8")

        config = load_config(temp_config_path)

        assert config.data_sources.a_shares.token == ""
        assert config.data_sources.a_shares.get_token() == "env-test-tushare-token"

    def test_env_var_priority_over_file(
        self,
        temp_config_path: Path,
        env_with_api_key,
    ):
        """测试环境变量优先级高于配置文件"""
        # 配置文件中设置了 api_key
        config_content = """
llm_api:
  provider: "deepseek"
  api_key: "file-api-key"
  model: "deepseek-v4-flash"
  temperature: 0

targets:
  - ticker: "TEST.SH"
    name: "测试"
    thesis: "测试信念"
"""
        temp_config_path.write_text(config_content, encoding="utf-8")

        config = load_config(temp_config_path)

        # 环境变量供 getter 使用，但不覆盖配置对象中的文件值
        assert config.llm_api.api_key == "file-api-key"
        assert config.llm_api.get_api_key() == "env-test-api-key"


class TestConfigManager:
    """ConfigManager 测试类"""

    def test_config_manager_load(self, temp_config_path: Path, sample_config_yaml_content: str):
        """测试 ConfigManager.load()"""
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        manager = ConfigManager(temp_config_path)
        config = manager.load()

        assert config.llm_api.provider == "deepseek"
        assert len(config.targets) == 1

    def test_config_manager_get_config_cached(
        self, temp_config_path: Path, sample_config_yaml_content: str
    ):
        """测试 ConfigManager.get_config() 缓存机制"""
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        manager = ConfigManager(temp_config_path)
        config1 = manager.get_config()
        config2 = manager.get_config()

        # 应该返回相同的对象（缓存）
        assert config1 is config2

    def test_config_manager_reload(
        self, temp_config_path: Path, sample_config_yaml_content: str
    ):
        """测试 ConfigManager.reload() 强制重新加载"""
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        manager = ConfigManager(temp_config_path)
        config1 = manager.get_config()

        # 修改配置文件
        new_content = sample_config_yaml_content.replace("中国核电", "中国船舶")
        temp_config_path.write_text(new_content, encoding="utf-8")

        # 重新加载
        config2 = manager.reload()

        assert config2.targets[0].name == "中国船舶"
        assert config1 is not config2

    def test_config_manager_get_targets(
        self, temp_config_path: Path, sample_config_yaml_content: str
    ):
        """测试 ConfigManager.get_targets()"""
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        manager = ConfigManager(temp_config_path)
        targets = manager.get_targets()

        assert len(targets) == 1
        assert targets[0].ticker == "601985.SH"


class TestGlobalConfig:
    """全局配置测试类"""

    def setup_method(self):
        """每个测试前重置全局配置"""
        reset_global_config()

    def teardown_method(self):
        """每个测试后重置全局配置"""
        reset_global_config()

    def test_get_config_singleton(
        self, temp_config_path: Path, sample_config_yaml_content: str
    ):
        """测试 get_config() 单例模式"""
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        config1 = get_config(temp_config_path)
        config2 = get_config()  # 不传路径，使用缓存

        assert config1 is config2

    def test_get_config_reload(
        self, temp_config_path: Path, sample_config_yaml_content: str
    ):
        """测试 get_config(reload=True)"""
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        config1 = get_config(temp_config_path)

        # 修改配置文件
        new_content = sample_config_yaml_content.replace("中国核电", "测试公司")
        temp_config_path.write_text(new_content, encoding="utf-8")

        # 强制重新加载
        config2 = get_config(temp_config_path, reload=True)

        assert config2.targets[0].name == "测试公司"

    def test_set_global_config(self, sample_app_config: AppConfig):
        """测试 set_global_config()"""
        set_global_config(sample_app_config)

        config = get_config()
        assert config is sample_app_config

    def test_reset_global_config(
        self, temp_config_path: Path, sample_config_yaml_content: str
    ):
        """测试 reset_global_config()"""
        temp_config_path.write_text(sample_config_yaml_content, encoding="utf-8")

        config1 = get_config(temp_config_path)
        reset_global_config()
        config2 = get_config(temp_config_path)

        # 重置后应该是新对象
        assert config1 is not config2


class TestTargetConfig:
    """TargetConfig 测试类"""

    def test_target_config_creation(self):
        """测试创建 TargetConfig"""
        target = TargetConfig(
            ticker="601985.SH",
            name="中国核电",
            thesis="核电是清洁能源的未来",
        )

        assert target.ticker == "601985.SH"
        assert target.name == "中国核电"
        assert target.industry == "未知"  # 默认值

    def test_target_config_ticker_normalization(self):
        """测试 ticker 规范化（转大写、去空格）"""
        target = TargetConfig(
            ticker="  aapl  ",
            name="Apple",
            thesis="科技巨头",
        )

        assert target.ticker == "AAPL"

    def test_target_config_get_market_a_share(self):
        """测试识别 A 股市场"""
        targets = [
            TargetConfig(ticker="601985.SH", name="上海", thesis="测试"),
            TargetConfig(ticker="000001.SZ", name="深圳", thesis="测试"),
        ]

        for target in targets:
            assert target.get_market() == "a_share"

    def test_target_config_get_market_hk(self):
        """测试识别港股市场"""
        target = TargetConfig(
            ticker="0700.HK",
            name="腾讯",
            thesis="测试",
        )

        assert target.get_market() == "hk"

    def test_target_config_get_market_us(self):
        """测试识别美股市场"""
        target = TargetConfig(
            ticker="AAPL",
            name="Apple",
            thesis="测试",
        )

        assert target.get_market() == "us"


class TestGapThresholdConfig:
    """GapThresholdConfig 测试类"""

    def test_default_thresholds(self):
        """测试默认阈值"""
        thresholds = GapThresholdConfig()

        assert thresholds.opportunity_gap_min == 10.0
        assert thresholds.opportunity_sentiment_max == 40
        assert thresholds.overheated_sentiment_min == 80

    def test_custom_thresholds(self):
        """测试自定义阈值"""
        thresholds = GapThresholdConfig(
            opportunity_gap_min=15.0,
            opportunity_sentiment_max=35,
            overheated_sentiment_min=85,
        )

        assert thresholds.opportunity_gap_min == 15.0
        assert thresholds.opportunity_sentiment_max == 35
        assert thresholds.overheated_sentiment_min == 85

    def test_threshold_validation_error(self):
        """测试阈值验证错误（opportunity_sentiment_max >= overheated_sentiment_min）"""
        with pytest.raises(ValueError) as exc_info:
            GapThresholdConfig(
                opportunity_sentiment_max=80,  # 等于过热阈值
                overheated_sentiment_min=80,
            )

        assert "应小于" in str(exc_info.value)


class TestAppConfig:
    """AppConfig 测试类"""

    def test_get_target_by_ticker(self, sample_app_config: AppConfig):
        """测试根据 ticker 获取标的配置"""
        target = sample_app_config.get_target_by_ticker("601985.SH")

        assert target is not None
        assert target.name == "中国核电"

    def test_get_target_by_ticker_not_found(self, sample_app_config: AppConfig):
        """测试 ticker 不存在"""
        target = sample_app_config.get_target_by_ticker("UNKNOWN")

        assert target is None

    def test_get_target_by_ticker_case_insensitive(self, sample_app_config: AppConfig):
        """测试 ticker 查找不区分大小写"""
        target = sample_app_config.get_target_by_ticker("601985.sh")

        assert target is not None
        assert target.name == "中国核电"

    def test_get_tickers(self, sample_app_config: AppConfig):
        """测试获取所有 ticker 列表"""
        tickers = sample_app_config.get_tickers()

        assert len(tickers) == 1
        assert "601985.SH" in tickers

    def test_duplicate_tickers_error(self):
        """测试重复 ticker 验证错误"""
        with pytest.raises(ValueError) as exc_info:
            AppConfig(
                targets=[
                    TargetConfig(ticker="AAPL", name="Apple1", thesis="测试1"),
                    TargetConfig(ticker="AAPL", name="Apple2", thesis="测试2"),
                ]
            )

        assert "重复的 ticker" in str(exc_info.value)


class TestLLMConfig:
    """LLMConfig 测试类"""

    def test_get_api_key_ignores_config_secret(self, clean_env):
        """运行期 secret 只从环境变量读取，不从 AppConfig 字段读取。"""
        config = LLMConfig(api_key="test-key")

        with pytest.raises(ValueError):
            config.get_api_key()

    def test_get_api_key_from_env(self, env_with_api_key):
        """测试从环境变量获取 API Key"""
        config = LLMConfig(api_key="")

        assert config.get_api_key() == "env-test-api-key"

    def test_get_api_key_env_priority(self, env_with_api_key):
        """测试环境变量优先级"""
        config = LLMConfig(api_key="config-key")

        # 环境变量应该优先
        assert config.get_api_key() == "env-test-api-key"

    def test_get_api_key_missing(self, clean_env):
        """测试 API Key 缺失时抛出错误"""
        config = LLMConfig(api_key="")

        with pytest.raises(ValueError) as exc_info:
            config.get_api_key()

        assert "未配置 DeepSeek API Key" in str(exc_info.value)

    def test_temperature_warning(self):
        """测试非零温度警告"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            LLMConfig(temperature=0.5)

            assert len(w) == 1
            assert "temperature" in str(w[0].message)


class TestTextSourceConfig:
    """TextSourceConfig 测试类"""

    def test_default_values(self):
        """测试默认配置值"""
        from src.config.models import TextSourceConfig

        config = TextSourceConfig()

        # A 股默认启用所有数据源
        assert "research" in config.a_share.enabled_sources
        assert "irm" in config.a_share.enabled_sources
        assert "rating" in config.a_share.enabled_sources
        assert "news" in config.a_share.enabled_sources

        # 默认权重
        assert config.a_share.quota_weights["research"] == 4
        assert config.a_share.quota_weights["irm"] == 3
        assert config.a_share.quota_weights["rating"] == 2
        assert config.a_share.quota_weights["news"] == 3

    def test_custom_a_share_config(self):
        """测试自定义 A 股配置"""
        config = load_config_from_dict({
            "targets": [],
            "data_sources": {
                "text": {
                    "a_share": {
                        "enabled_sources": ["research", "news"],
                        "quota_weights": {
                            "research": 6,
                            "news": 4,
                        }
                    }
                }
            }
        })

        assert config.data_sources.text.a_share.enabled_sources == ["research", "news"]
        assert config.data_sources.text.a_share.quota_weights["research"] == 6

    def test_backward_compatibility_ignores_old_fields(self):
        """测试向后兼容：旧字段被静默忽略并发出警告"""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # 这不应该抛出异常
            config = load_config_from_dict({
                "targets": [],
                "data_sources": {
                    "text": {
                        # 旧字段（应被忽略）
                        "research_providers": ["中信证券"],
                        "news_sites": ["东方财富"],
                        "search_entrypoints": ["https://example.com"],
                        # 新字段
                        "a_share": {
                            "enabled_sources": ["research"]
                        }
                    }
                }
            })

            # 新字段正常工作
            assert config.data_sources.text.a_share.enabled_sources == ["research"]

            # 旧字段不应存在
            assert not hasattr(config.data_sources.text, "research_providers")
            assert not hasattr(config.data_sources.text, "news_sites")
            assert not hasattr(config.data_sources.text, "search_entrypoints")

            # 应该有废弃警告
            deprecation_warnings = [
                warning for warning in w
                if issubclass(warning.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1
            assert "已废弃" in str(deprecation_warnings[0].message)

    def test_hk_us_config_preserved(self):
        """测试港美股配置正确保留"""
        config = load_config_from_dict({
            "targets": [],
            "data_sources": {
                "text": {
                    "hk_us": {
                        # serpapi 是非默认的合法 provider，用于验证用户显式配置被保留
                        "search_provider": "serpapi",
                        "trusted_domains": ["bloomberg.com", "wsj.com"]
                    }
                }
            }
        })

        assert config.data_sources.text.hk_us.search_provider == "serpapi"
        assert "bloomberg.com" in config.data_sources.text.hk_us.trusted_domains
        assert "wsj.com" in config.data_sources.text.hk_us.trusted_domains

    def test_hk_us_default_values(self):
        """测试港美股配置默认值"""
        from src.config.models import TextSourceConfig

        config = TextSourceConfig()

        assert config.hk_us.search_provider == "serper"
        assert config.hk_us.search_api_key == ""
        assert "bloomberg.com" in config.hk_us.trusted_domains
        assert "reuters.com" in config.hk_us.trusted_domains
        assert "seekingalpha.com" in config.hk_us.trusted_domains
