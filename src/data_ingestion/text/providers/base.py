"""
数据提供者基类和注册机制

定义数据提供者的抽象接口和注册表，支持多种数据源的统一管理。
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Literal

from ...models import TextItem


class ProviderType(str, Enum):
    """数据提供者类型枚举"""

    MOCK = "mock"  # Mock 数据（开发测试）
    AKSHARE = "akshare"  # AkShare API（A股）
    LLM_AGENT = "llm_agent"  # LLM Agent（港美股/复杂场景）


class DataProvider(ABC):
    """
    数据提供者抽象基类

    定义所有数据提供者必须实现的接口，包括获取新闻、研报数据以及可用性检查。
    """

    # 提供者类型标识
    provider_type: ProviderType

    # 支持的市场类型
    supported_markets: list[Literal["a_share", "hk", "us"]]

    @abstractmethod
    def fetch_news(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取新闻数据

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"
            lookback_hours: 回溯时间窗口（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 新闻列表
        """
        pass

    @abstractmethod
    def fetch_research(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
    ) -> list[TextItem]:
        """
        获取研报数据

        Args:
            ticker: 证券代码，如 "601985.SH"
            name: 标的名称，如 "中国核电"
            lookback_hours: 回溯时间窗口（小时）
            max_items: 最大返回条数

        Returns:
            list[TextItem]: 研报列表
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        检查数据源是否可用

        Returns:
            bool: 是否可用（API 可达、配置正确等）
        """
        pass

    def supports_market(self, ticker: str) -> bool:
        """
        检查是否支持该市场

        Args:
            ticker: 证券代码

        Returns:
            bool: 是否支持
        """
        market = self._detect_market(ticker)
        return market in self.supported_markets

    @staticmethod
    def _detect_market(ticker: str) -> Literal["a_share", "hk", "us"]:
        """
        根据 ticker 后缀检测市场类型

        Args:
            ticker: 证券代码

        Returns:
            Literal["a_share", "hk", "us"]: 市场类型
        """
        ticker_upper = ticker.upper()
        if ticker_upper.endswith((".SH", ".SZ")):
            return "a_share"
        elif ticker_upper.endswith(".HK"):
            return "hk"
        else:
            return "us"


class ProviderRegistry:
    """
    数据提供者注册表

    管理数据提供者的注册和实例化，支持通过装饰器注册和工厂方法创建实例。
    """

    _providers: dict[ProviderType, type[DataProvider]] = {}

    @classmethod
    def register(cls, provider_type: ProviderType):
        """
        装饰器：注册数据提供者

        Args:
            provider_type: 提供者类型

        Returns:
            装饰器函数

        Example:
            @ProviderRegistry.register(ProviderType.MOCK)
            class MockDataProvider(DataProvider):
                ...
        """

        def decorator(provider_class: type[DataProvider]):
            cls._providers[provider_type] = provider_class
            return provider_class

        return decorator

    @classmethod
    def get(cls, provider_type: ProviderType) -> type[DataProvider] | None:
        """
        获取数据提供者类

        Args:
            provider_type: 提供者类型

        Returns:
            type[DataProvider] | None: 提供者类，未注册则返回 None
        """
        return cls._providers.get(provider_type)

    @classmethod
    def create(
        cls,
        provider_type: ProviderType,
        **kwargs,
    ) -> DataProvider:
        """
        创建数据提供者实例

        Args:
            provider_type: 提供者类型
            **kwargs: 传递给提供者构造函数的参数

        Returns:
            DataProvider: 提供者实例

        Raises:
            ValueError: 如果提供者类型未注册
        """
        provider_class = cls.get(provider_type)
        if not provider_class:
            raise ValueError(f"未注册的数据提供者: {provider_type}")
        return provider_class(**kwargs)

    @classmethod
    def list_available(cls) -> list[ProviderType]:
        """
        列出所有已注册的提供者类型

        Returns:
            list[ProviderType]: 已注册的提供者类型列表
        """
        return list(cls._providers.keys())
