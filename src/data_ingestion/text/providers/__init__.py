"""
数据提供者模块

提供统一的数据获取接口，支持多种数据源。
"""
from .base import DataProvider, ProviderRegistry, ProviderType

__all__ = [
    "DataProvider",
    "ProviderType",
    "ProviderRegistry",
]
