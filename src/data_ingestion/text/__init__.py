"""
文本数据采集模块

提供统一的文本数据获取接口，支持 A 股和港美股市场。
"""

from .base import TextProvider
from .factory import TextProviderFactory
from .mock_provider import MockTextProvider
from .models import FetchResult, TextSourceType

# A 股 Provider（如需直接使用）
from .a_share import AShareTextProvider

__all__ = [
    # 核心接口
    "TextProvider",
    "TextProviderFactory",
    # 数据模型
    "TextSourceType",
    "FetchResult",
    # 具体实现
    "AShareTextProvider",
    "MockTextProvider",
]
