"""
配置管理器 - 负责加载和解析 config.yaml
"""
import os
from pathlib import Path

from .models import AppConfig


class ConfigManager:
    """配置管理器，提供统一配置对象"""

    def __init__(self, config_path: str | Path | None = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径，默认为项目根目录下的 config.yaml
        """
        self._config_path = Path(config_path) if config_path else Path("config.yaml")
        self._config: AppConfig | None = None

    def load(self) -> AppConfig:
        """
        加载配置文件

        Returns:
            AppConfig: 解析后的配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置格式错误
        """
        # TODO: 实现 YAML 加载逻辑
        # 1. 读取 YAML 文件
        # 2. 解析为 dict
        # 3. 转换为 AppConfig 数据类
        # 4. 处理环境变量注入 (api_key 等)
        raise NotImplementedError

    def get_config(self) -> AppConfig:
        """
        获取已加载的配置，若未加载则自动加载

        Returns:
            AppConfig: 配置对象
        """
        if self._config is None:
            self._config = self.load()
        return self._config

    def get_api_key(self) -> str:
        """
        获取 LLM API Key，优先从环境变量读取

        Returns:
            str: API Key
        """
        config = self.get_config()
        return os.environ.get("DEEPSEEK_API_KEY", config.llm_api.api_key)

    def get_targets(self) -> list:
        """
        获取所有监控标的配置

        Returns:
            list[TargetConfig]: 标的配置列表
        """
        return self.get_config().targets
