"""
配置模块

提供应用配置的加载和管理功能。
支持从 config.yaml 加载配置并进行类型校验。
"""
from .manager import (
    ConfigManager,
    ConfigError,
    load_config,
    load_config_from_dict,
    get_config,
    set_global_config,
    reset_global_config,
)
from .models import (
    AppConfig,
    LLMConfig,
    DataSourcesConfig,
    ASharesSourceConfig,
    HKUSSourceConfig,
    QuotesSourceConfig,
    TextSourceConfig,
    TrustedSourcesConfig,
    CrawlerConfig,
    TargetConfig,
    OutputConfig,
    PersistenceConfig,
    SchedulerConfig,
    GapThresholdConfig,
    RiskControlConfig,
)

__all__ = [
    # Manager
    "ConfigManager",
    "ConfigError",
    "load_config",
    "load_config_from_dict",
    "get_config",
    "set_global_config",
    "reset_global_config",
    # Models
    "AppConfig",
    "LLMConfig",
    "DataSourcesConfig",
    "ASharesSourceConfig",
    "HKUSSourceConfig",
    "QuotesSourceConfig",
    "TextSourceConfig",
    "TrustedSourcesConfig",
    "CrawlerConfig",
    "TargetConfig",
    "OutputConfig",
    "PersistenceConfig",
    "SchedulerConfig",
    "GapThresholdConfig",
    "RiskControlConfig",
]
