"""
配置模块

提供应用配置的加载和管理功能。
"""
from .manager import ConfigManager, ConfigError, load_config, load_config_from_dict
from .models import (
    AppConfig,
    LLMConfig,
    DataSourcesConfig,
    QuotesSourceConfig,
    TextSourceConfig,
    TrustedSourcesConfig,
    CrawlerConfig,
    TargetConfig,
    SchedulerConfig,
    GapThresholdConfig,
)

__all__ = [
    # Manager
    "ConfigManager",
    "ConfigError",
    "load_config",
    "load_config_from_dict",
    # Models
    "AppConfig",
    "LLMConfig",
    "DataSourcesConfig",
    "QuotesSourceConfig",
    "TextSourceConfig",
    "TrustedSourcesConfig",
    "CrawlerConfig",
    "TargetConfig",
    "SchedulerConfig",
    "GapThresholdConfig",
]
