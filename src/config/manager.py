"""
配置管理器 - 负责加载和解析 config.yaml

提供 load_config() 便捷函数和 ConfigManager 类，
支持从 YAML 文件加载配置并转换为类型安全的 Pydantic 模型。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import AppConfig, TargetConfig


class ConfigError(Exception):
    """配置加载错误"""

    pass


class ConfigManager:
    """
    配置管理器，提供统一配置对象

    支持从 YAML 文件加载配置，自动处理环境变量注入，
    并提供缓存机制避免重复加载。

    Example:
        >>> manager = ConfigManager("config.yaml")
        >>> config = manager.load()
        >>> print(config.targets[0].ticker)
        601985.SH
    """

    def __init__(self, config_path: str | Path | None = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径，默认为项目根目录下的 config.yaml
        """
        self._config_path = Path(config_path) if config_path else Path("config.yaml")
        self._config: AppConfig | None = None

    @property
    def config_path(self) -> Path:
        """获取配置文件路径"""
        return self._config_path

    def load(self) -> AppConfig:
        """
        加载配置文件

        从 YAML 文件读取配置，解析并验证后返回 AppConfig 对象。
        API Key 支持从环境变量 DEEPSEEK_API_KEY 注入。

        Returns:
            AppConfig: 解析后的配置对象

        Raises:
            ConfigError: 配置文件不存在或格式错误
        """
        # 检查文件是否存在
        if not self._config_path.exists():
            raise ConfigError(f"配置文件不存在: {self._config_path}")

        # 读取 YAML 文件
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML 解析错误: {e}")

        if raw_config is None:
            raw_config = {}

        # 处理环境变量注入
        raw_config = self._inject_env_vars(raw_config)

        # 转换为 Pydantic 模型
        try:
            self._config = AppConfig.model_validate(raw_config)
        except ValidationError as e:
            raise ConfigError(f"配置验证失败:\n{e}")

        return self._config

    def _inject_env_vars(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        注入环境变量到配置中

        优先级: 环境变量 > 配置文件中的值

        Args:
            config: 原始配置字典

        Returns:
            dict: 注入环境变量后的配置
        """
        # 确保 llm_api 存在
        if "llm_api" not in config:
            config["llm_api"] = {}

        # 从环境变量注入 API Key
        env_api_key = os.environ.get("DEEPSEEK_API_KEY")
        if env_api_key:
            config["llm_api"]["api_key"] = env_api_key

        # 从环境变量注入 Tushare Token（如果需要）
        env_tushare_token = os.environ.get("TUSHARE_TOKEN")
        if env_tushare_token:
            if "data_sources" not in config:
                config["data_sources"] = {}
            if "quotes" not in config["data_sources"]:
                config["data_sources"]["quotes"] = {}
            config["data_sources"]["quotes"]["tushare_token"] = env_tushare_token

        return config

    def get_config(self) -> AppConfig:
        """
        获取已加载的配置，若未加载则自动加载

        Returns:
            AppConfig: 配置对象
        """
        if self._config is None:
            self._config = self.load()
        return self._config

    def reload(self) -> AppConfig:
        """
        强制重新加载配置

        Returns:
            AppConfig: 新加载的配置对象
        """
        self._config = None
        return self.load()

    def get_api_key(self) -> str:
        """
        获取 LLM API Key

        Returns:
            str: API Key

        Raises:
            ValueError: 未配置 API Key
        """
        return self.get_config().llm_api.get_api_key()

    def get_targets(self) -> list[TargetConfig]:
        """
        获取所有监控标的配置

        Returns:
            list[TargetConfig]: 标的配置列表
        """
        return self.get_config().targets


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """
    便捷函数：加载配置文件

    这是加载配置的推荐入口函数，直接返回 AppConfig 对象。

    Args:
        path: 配置文件路径，默认为 "config.yaml"

    Returns:
        AppConfig: 解析后的配置对象

    Raises:
        ConfigError: 配置文件不存在或格式错误

    Example:
        >>> config = load_config("config.yaml")
        >>> print(config.llm_api.model)
        deepseek-chat

        >>> for target in config.targets:
        ...     print(f"{target.ticker}: {target.name}")
        601985.SH: 中国核电
        600150.SH: 中国船舶
    """
    manager = ConfigManager(path)
    return manager.load()


def load_config_from_dict(data: dict[str, Any]) -> AppConfig:
    """
    从字典加载配置

    用于测试或程序化构建配置。

    Args:
        data: 配置字典

    Returns:
        AppConfig: 解析后的配置对象

    Raises:
        ConfigError: 配置验证失败

    Example:
        >>> config = load_config_from_dict({
        ...     "targets": [
        ...         {"ticker": "AAPL", "name": "Apple", "thesis": "..."}
        ...     ]
        ... })
    """
    try:
        return AppConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"配置验证失败:\n{e}")
