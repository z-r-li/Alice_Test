"""
配置管理器 - 负责加载和解析 config.yaml

提供 load_config() 便捷函数和 ConfigManager 类，
支持从 YAML 文件加载配置并转换为类型安全的 Pydantic 模型。

全局配置访问：
    使用 get_config() 获取全局配置单例。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import AppConfig, TargetConfig

# 全局配置单例
_global_config: AppConfig | None = None


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

        优先级: 配置文件显式值 > 环境变量 > 默认值

        显式写在 YAML 中的值（包括空字符串以外的任何值）总是优先生效；
        环境变量仅在 YAML 缺省时作为回退使用。这便于本地用 YAML 覆盖
        全局 shell 环境变量进行测试。

        Args:
            config: 原始配置字典

        Returns:
            dict: 注入环境变量后的配置
        """
        if "llm_api" not in config:
            config["llm_api"] = {}

        # DEEPSEEK_API_KEY: 仅在 YAML 未显式提供时回填
        env_api_key = os.environ.get("DEEPSEEK_API_KEY")
        if env_api_key and not config["llm_api"].get("api_key"):
            config["llm_api"]["api_key"] = env_api_key

        # TUSHARE_TOKEN: 仅在 YAML 未显式提供时回填
        env_tushare_token = os.environ.get("TUSHARE_TOKEN")
        if env_tushare_token:
            config.setdefault("data_sources", {}).setdefault("a_shares", {})
            if not config["data_sources"]["a_shares"].get("token"):
                config["data_sources"]["a_shares"]["token"] = env_tushare_token

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


def get_config(path: str | Path | None = None, reload: bool = False) -> AppConfig:
    """
    获取全局配置单例

    提供一个可全局访问的 Config 对象。首次调用时会从指定路径加载配置，
    后续调用将返回缓存的配置对象（除非指定 reload=True）。

    Args:
        path: 配置文件路径，默认为 "config.yaml"。仅在首次加载或 reload 时使用。
        reload: 是否强制重新加载配置

    Returns:
        AppConfig: 全局配置对象

    Raises:
        ConfigError: 配置文件不存在或格式错误

    Example:
        >>> # 首次加载
        >>> config = get_config("config.yaml")
        >>> print(config.llm_api.model)
        deepseek-chat

        >>> # 后续访问（使用缓存）
        >>> config = get_config()
        >>> print(config.targets[0].ticker)
        601985.SH

        >>> # 强制重新加载
        >>> config = get_config(reload=True)
    """
    global _global_config

    if _global_config is None or reload:
        config_path = path or "config.yaml"
        _global_config = load_config(config_path)

    return _global_config


def set_global_config(config: AppConfig) -> None:
    """
    设置全局配置对象

    用于测试或程序化设置配置。

    Args:
        config: 配置对象

    Example:
        >>> config = load_config_from_dict({"targets": [...]})
        >>> set_global_config(config)
    """
    global _global_config
    _global_config = config


def reset_global_config() -> None:
    """
    重置全局配置

    清除缓存的全局配置对象，下次调用 get_config() 时将重新加载。
    主要用于测试场景。
    """
    global _global_config
    _global_config = None
