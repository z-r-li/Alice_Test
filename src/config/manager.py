"""
配置管理器 - 负责加载和解析 config.yaml

提供 load_config() 便捷函数和 ConfigManager 类，
支持从 YAML 文件加载配置并转换为类型安全的 Pydantic 模型。

全局配置访问：
    使用 get_config() 获取全局配置单例。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .env_interpolation import EnvPlaceholderError, interpolate_config
from .models import AppConfig, TargetConfig

# 全局配置单例
_global_config: AppConfig | None = None


class ConfigError(Exception):
    """配置加载错误"""

    pass


class ConfigManager:
    """
    配置管理器，提供统一配置对象

    支持从 YAML 文件加载配置，并提供缓存机制避免重复加载。

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
        Secret 不写入配置对象；运行期由各配置 getter 直接从 os.environ 读取。

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

        # Secret 不注入 raw_config，避免真实值驻留 AppConfig。
        raw_config = self._prepare_config(raw_config)

        # 转换为 Pydantic 模型
        try:
            self._config = AppConfig.model_validate(raw_config)
        except ValidationError as e:
            raise ConfigError(f"配置验证失败:\n{e}")

        return self._config

    def _prepare_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        加载前预处理配置：解析**非密钥**字段的 ``${ENV}`` 占位（CDX-5 / D-20260629-2 B 案）。

        - **${ENV} 插值**：非密钥字段的字符串值在此把 ``${VAR}`` 解析为环境变量值；
          被引用的 env 缺失即 fail-closed 抛 ``ConfigError``（报文含缺失的 ``VAR`` 名），
          绝不静默置空。
        - **密钥不驻留**：密钥类字段（``api_key`` / ``token`` / ``secret`` …）的 ``${VAR}``
          **不在此解析**（``interpolate_config`` 跳过这些键），占位原样保留；运行期由各
          getter（``get_api_key`` / ``get_token``）即时解析、绝不写回 ``AppConfig``。
          环境变量中的 secret 同样不写回配置字典。

        Args:
            config: 原始配置字典

        Returns:
            dict: ``${ENV}`` 占位解析后的配置

        Raises:
            ConfigError: 非密钥字段的 ``${ENV}`` 占位引用了未设置的环境变量
        """
        try:
            return interpolate_config(config)
        except EnvPlaceholderError as e:
            raise ConfigError(str(e)) from e

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
        deepseek-v4-flash

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
        deepseek-v4-flash

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
