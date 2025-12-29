"""
文本 Provider 工厂

根据 ticker 后缀自动选择合适的 Provider。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import TextProvider
from .models import TextSourceType

if TYPE_CHECKING:
    from ..models import TextItem

logger = logging.getLogger("alice_test")


class _PlaceholderProvider(TextProvider):
    """
    占位 Provider

    用于港美股市场尚未实现的 Provider。
    所有方法均返回空结果并记录警告。
    """

    def __init__(self, market: str):
        self._market = market

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """返回空列表并记录警告"""
        logger.warning(
            f"[{ticker}] {self._market} 市场 Provider 尚未实现，返回空列表"
        )
        return []

    def get_source_name(self) -> str:
        return f"{self._market}_placeholder"

    def supports_market(self, ticker: str) -> bool:
        """占位 Provider 根据市场类型判断"""
        market = self.detect_market(ticker)
        if self._market == "hk_us":
            return market in ("hk", "us")
        return False

    def get_supported_source_types(self) -> list[TextSourceType]:
        """占位 Provider 暂不支持任何类型"""
        return []


class TextProviderFactory:
    """
    文本 Provider 工厂

    根据 ticker 后缀自动选择合适的 Provider：
    - .SH / .SZ -> AShareTextProvider (AkShareTextProvider)
    - .HK / 无后缀 -> HKUSTextProvider (暂未实现，返回占位)

    使用单例模式缓存 Provider 实例。

    Example:
        >>> # 获取 A 股 Provider
        >>> provider = TextProviderFactory.get_provider("601985.SH")
        >>> texts = provider.fetch_texts("601985.SH", "中国核电")
        >>>
        >>> # 使用便捷方法（推荐）
        >>> texts = TextProviderFactory.fetch_texts("601985.SH", "中国核电")
    """

    _a_share_provider: TextProvider | None = None
    _hk_us_provider: TextProvider | None = None

    @classmethod
    def get_provider(cls, ticker: str) -> TextProvider:
        """
        根据 ticker 返回对应的 Provider 实例

        Args:
            ticker: 证券代码，如 "601985.SH"、"0700.HK"、"AAPL"

        Returns:
            TextProvider: 对应市场的 Provider 实例

        Example:
            >>> provider = TextProviderFactory.get_provider("601985.SH")
            >>> provider.get_source_name()
            'akshare'
        """
        market = TextProvider.detect_market(ticker)

        if market == "a_share":
            return cls._get_a_share_provider()
        else:
            # 港股和美股暂时使用同一个占位 Provider
            return cls._get_hk_us_provider()

    @classmethod
    def _get_a_share_provider(cls) -> TextProvider:
        """获取或创建 A 股 Provider（单例）"""
        if cls._a_share_provider is None:
            # 延迟导入避免循环依赖
            from .akshare_provider import AkShareTextProvider

            cls._a_share_provider = AkShareTextProvider(
                llm_client=None,
                extract_pdf=False,  # 默认不提取 PDF，避免依赖 LLM
            )
            logger.info("创建 A 股 TextProvider (AkShareTextProvider)")

        return cls._a_share_provider

    @classmethod
    def _get_hk_us_provider(cls) -> TextProvider:
        """获取或创建港美股 Provider（单例）"""
        if cls._hk_us_provider is None:
            cls._hk_us_provider = _PlaceholderProvider("hk_us")
            logger.info("创建港美股 TextProvider (占位实现)")

        return cls._hk_us_provider

    @classmethod
    def fetch_texts(
        cls,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        便捷方法：自动选择 Provider 并获取文本

        这是推荐的调用入口。根据 ticker 自动选择合适的 Provider，
        然后调用其 fetch_texts 方法获取文本数据。

        Args:
            ticker: 证券代码，如 "601985.SH"、"AAPL"
            name: 标的名称（用于搜索）
            lookback_hours: 回溯时间窗口（小时），默认 48 小时
            max_items: 最大返回条数，默认 10 条
            source_types: 可选的数据源类型过滤列表，为 None 时返回所有类型

        Returns:
            list[TextItem]: 文本数据列表，按相关性/时间排序

        Example:
            >>> texts = TextProviderFactory.fetch_texts(
            ...     ticker="601985.SH",
            ...     name="中国核电",
            ...     lookback_hours=24,
            ...     max_items=5,
            ... )
            >>> len(texts)
            5
        """
        # 延迟导入避免循环依赖
        from ..models import TextItem

        provider = cls.get_provider(ticker)
        return provider.fetch_texts(
            ticker=ticker,
            name=name,
            lookback_hours=lookback_hours,
            max_items=max_items,
            source_types=source_types,
        )

    @classmethod
    def reset(cls) -> None:
        """
        重置缓存的 Provider 实例

        主要用于测试场景，清除单例缓存以便重新初始化。

        Example:
            >>> TextProviderFactory.reset()
            >>> # 下次调用 get_provider 会创建新实例
        """
        cls._a_share_provider = None
        cls._hk_us_provider = None
        logger.debug("TextProviderFactory 缓存已重置")
