"""
A 股文本数据聚合 Provider

整合多个数据源（研报、互动易、评级变动、新闻），
提供统一的文本获取接口。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..base import TextProvider
from ..models import FetchResult, TextSourceType
from .irm_fetcher import IRMFetcher
from .news_fetcher import NewsFetcher
from .rating_fetcher import RatingFetcher
from .research_fetcher import ResearchFetcher

if TYPE_CHECKING:
    from ....models import TextItem

logger = logging.getLogger("alice_test")


class AShareTextProvider(TextProvider):
    """
    A 股文本数据聚合 Provider

    整合多个数据源，按配置的优先级和配额获取文本。

    默认配额分配（总计 10 条时）：
    - 研报: 4 条 (implied_growth 推算依据)
    - 互动易: 3 条 (key_worry 直接来源)
    - 评级变动: 2 条 (预期转向信号)
    - 新闻: 3 条 (叙事补充)

    Example:
        >>> provider = AShareTextProvider()
        >>> texts = provider.fetch_texts(
        ...     ticker="601985.SH",
        ...     name="中国核电",
        ...     lookback_hours=72,
        ...     max_items=10,
        ... )
        >>> print(f"获取 {len(texts)} 条文本")
    """

    # 默认配额权重
    DEFAULT_WEIGHTS: dict[TextSourceType, int] = {
        TextSourceType.RESEARCH: 4,
        TextSourceType.IRM: 3,
        TextSourceType.RATING: 2,
        TextSourceType.NEWS: 3,
    }

    # 排序优先级（数值越大越靠前）
    SOURCE_PRIORITY: dict[TextSourceType, int] = {
        TextSourceType.RESEARCH: 4,
        TextSourceType.RATING: 3,
        TextSourceType.IRM: 2,
        TextSourceType.NEWS: 1,
    }

    def __init__(
        self,
        weights: dict[TextSourceType, int] | None = None,
    ):
        """
        初始化 A 股文本 Provider

        Args:
            weights: 自定义配额权重，不指定则使用默认值
        """
        self._weights = weights or self.DEFAULT_WEIGHTS.copy()
        self._news_fetcher = NewsFetcher()
        self._research_fetcher = ResearchFetcher()
        self._irm_fetcher = IRMFetcher()
        self._rating_fetcher = RatingFetcher()

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        聚合多数据源获取文本

        Args:
            ticker: 股票代码（如 "601985.SH"）
            name: 股票名称
            lookback_hours: 时间窗口
            max_items: 最大返回条数
            source_types: 指定数据源类型，None 表示使用全部

        Returns:
            list[TextItem]: 聚合并去重后的文本列表
        """
        # 延迟导入避免循环依赖
        from ...models import TextItem

        # 确定要使用的数据源
        active_sources = source_types or self.get_supported_source_types()
        active_sources = [s for s in active_sources if s in self.get_supported_source_types()]

        if not active_sources:
            logger.warning(f"[{ticker}] 没有有效的数据源类型")
            return []

        # 分配配额
        quotas = self._allocate_quota(active_sources, max_items)
        logger.debug(f"[{ticker}] 配额分配: {quotas}")

        # 提取纯代码
        symbol = self.extract_symbol(ticker)

        # 并行获取各数据源（这里串行执行，如需并行可用 ThreadPoolExecutor）
        all_items: list[TextItem] = []
        fetch_results: list[FetchResult] = []

        for source_type in active_sources:
            quota = quotas.get(source_type, 0)
            if quota <= 0:
                continue

            fetcher = self._get_fetcher(source_type)
            if fetcher is None:
                continue

            # 多取 FUTURE_GUARD_HEADROOM 条余量：fetcher 内部按 max_items 截断（含未来戳）
            # 发生在上界护栏之前，未来戳排在有效行前会先挤掉窗内有效行。多取 → drop_future
            # → 截回 quota，与 AShareTextCoordinator._collect 同一处理（常量释义见 TextProvider）。
            result = fetcher.fetch(
                ticker=ticker,
                symbol=symbol,
                name=name,
                lookback_hours=lookback_hours,
                max_items=quota + self.FUTURE_GUARD_HEADROOM,
            )
            fetch_results.append(result)

            if result.success and result.items:
                kept = self.drop_future_items(result.items, ticker)[:quota]
                all_items.extend(kept)
                logger.debug(
                    f"[{ticker}] {source_type.value}: 获取 {len(kept)}/{quota} 条"
                )
            elif not result.success:
                logger.warning(
                    f"[{ticker}] {source_type.value} 获取失败: {result.error_message}"
                )

        # 去重并排序
        final_items = self._dedupe_and_rank(all_items)

        # 限制返回条数
        if len(final_items) > max_items:
            final_items = final_items[:max_items]

        logger.info(
            f"[{ticker}] 聚合完成: 原始 {len(all_items)} 条, "
            f"去重后 {len(final_items)} 条"
        )

        return final_items

    def supports_market(self, ticker: str) -> bool:
        """支持 A 股市场（.SH / .SZ）"""
        return ticker.upper().endswith((".SH", ".SZ"))

    def get_supported_source_types(self) -> list[TextSourceType]:
        """返回支持的数据源类型"""
        return [
            TextSourceType.NEWS,
            TextSourceType.RESEARCH,
            TextSourceType.IRM,
            TextSourceType.RATING,
        ]

    def get_source_name(self) -> str:
        """获取数据源名称"""
        return "a_share_aggregated"

    def _allocate_quota(
        self,
        source_types: list[TextSourceType],
        total: int,
    ) -> dict[TextSourceType, int]:
        """
        智能配额分配

        根据权重比例分配每个数据源的配额，确保每个至少 1 条。

        Args:
            source_types: 需要分配配额的数据源类型列表
            total: 总配额

        Returns:
            dict[TextSourceType, int]: 每个数据源的配额
        """
        if not source_types:
            return {}

        # 如果总数小于数据源数量，每个源最多分配 1 条
        if total <= len(source_types):
            quotas = {}
            for i, source_type in enumerate(source_types):
                quotas[source_type] = 1 if i < total else 0
            return quotas

        # 计算有效权重总和
        active_weights = {
            st: self._weights.get(st, 1) for st in source_types
        }
        total_weight = sum(active_weights.values())

        if total_weight == 0:
            # 平均分配
            base = total // len(source_types)
            remainder = total % len(source_types)
            quotas = {}
            for i, source_type in enumerate(source_types):
                quotas[source_type] = base + (1 if i < remainder else 0)
            return quotas

        # 按权重分配，确保每个至少 1 条
        quotas: dict[TextSourceType, int] = {}
        remaining = total

        # 先给每个源分配 1 条
        for source_type in source_types:
            quotas[source_type] = 1
            remaining -= 1

        # 剩余按权重分配
        if remaining > 0:
            for source_type in source_types:
                weight = active_weights[source_type]
                extra = int((remaining * weight) / total_weight)
                quotas[source_type] += extra

            # 处理舍入误差：把剩余的分给权重最高的
            allocated = sum(quotas.values())
            diff = total - allocated
            if diff > 0:
                # 按权重排序，优先给权重高的
                sorted_sources = sorted(
                    source_types,
                    key=lambda x: active_weights[x],
                    reverse=True,
                )
                for i in range(diff):
                    quotas[sorted_sources[i % len(sorted_sources)]] += 1

        return quotas

    def _get_fetcher(
        self,
        source_type: TextSourceType,
    ) -> NewsFetcher | ResearchFetcher | IRMFetcher | RatingFetcher | None:
        """根据类型返回对应的 Fetcher"""
        fetcher_map = {
            TextSourceType.NEWS: self._news_fetcher,
            TextSourceType.RESEARCH: self._research_fetcher,
            TextSourceType.IRM: self._irm_fetcher,
            TextSourceType.RATING: self._rating_fetcher,
        }
        return fetcher_map.get(source_type)

    def _dedupe_and_rank(
        self,
        texts: list[TextItem],
    ) -> list[TextItem]:
        """
        去重并按价值排序

        去重规则：相同标题视为重复
        排序规则：研报 > 评级变动 > 互动易 > 新闻，同类型按时间倒序

        Args:
            texts: 原始文本列表

        Returns:
            list[TextItem]: 去重并排序后的列表
        """
        # 延迟导入
        from ...models import TextItem

        # 去重：相同标题视为重复，保留第一个（通常是优先级更高的源）
        seen_titles: set[str] = set()
        unique_texts: list[TextItem] = []

        for text in texts:
            # 标准化标题（去除空白）
            normalized_title = text.title.strip()
            if normalized_title not in seen_titles:
                seen_titles.add(normalized_title)
                unique_texts.append(text)

        # 排序：先按数据源优先级，再按时间倒序
        def sort_key(item: TextItem) -> tuple[int, float]:
            # 根据 type 字段推断 TextSourceType
            source_type = self._infer_source_type(item)
            priority = self.SOURCE_PRIORITY.get(source_type, 0)
            # 时间戳取负数实现倒序
            timestamp = item.published_at.timestamp()
            return (-priority, -timestamp)

        unique_texts.sort(key=sort_key)

        return unique_texts

    def _infer_source_type(self, item: TextItem) -> TextSourceType:
        """
        根据 TextItem 推断其数据源类型

        Args:
            item: 文本项

        Returns:
            TextSourceType: 推断的数据源类型
        """
        # 根据 type 字段判断
        if item.type == "research":
            # 进一步区分研报和评级
            # 评级变动的标题通常以 [上调]、[下调]、[维持]、[首次] 开头
            if item.title.startswith(("[上调]", "[下调]", "[维持]", "[首次]")):
                return TextSourceType.RATING
            return TextSourceType.RESEARCH
        elif item.type == "news":
            # 互动易的标题通常以 [投资者提问] 开头
            if item.title.startswith("[投资者提问]"):
                return TextSourceType.IRM
            return TextSourceType.NEWS

        # 默认返回新闻
        return TextSourceType.NEWS
