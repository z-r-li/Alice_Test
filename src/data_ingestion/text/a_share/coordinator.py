"""
A 股文本数据协调器

统一调度各文本数据源（研报、互动易、机构评级、新闻），
根据 ticker 类型自动选择正确的数据源，按配置权重分配配额。
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher
from logging import Logger
from typing import TYPE_CHECKING

from ....config.models import AShareTextSourceConfig
from ...models import TextItem
from ..base import TextProvider
from ..models import (
    SourceReachability,
    TextCoverage,
    TextSourceCoverage,
    TextSourceType,
)
from .announcement_fetcher import AnnouncementFetcher
from .cls_news_fetcher import CLSNewsFetcher
from .cninfo_irm_fetcher import CNInfoIRMFetcher
from .news_fetcher import NewsFetcher
from .profit_forecast_fetcher import ProfitForecastFetcher
from .rating_change_fetcher import RatingChangeFetcher
from .research_fetcher import ResearchFetcher
from .sse_interactive_fetcher import SSEInteractiveFetcher

if TYPE_CHECKING:
    pass


logger = logging.getLogger("alice_test")


class AShareTextCoordinator(TextProvider):
    """
    A股文本数据协调器

    职责：
    1. 根据 ticker 类型选择正确的数据源
    2. 按配置的权重分配各数据源配额
    3. 整合、去重、排序所有文本数据
    4. 实现优雅降级（某数据源失败不影响其他）

    数据源优先级（默认）：
    1. 研报 (research) - 最有价值
    2. 互动易 (irm) - 直接反映市场担忧
    3. 机构评级 (rating) - 预期变化信号
    4. 新闻 (news) - 补充叙事

    Example:
        >>> coordinator = AShareTextCoordinator()
        >>> texts = coordinator.fetch_texts(
        ...     ticker="601985.SH",
        ...     name="中国核电",
        ...     lookback_hours=48,
        ...     max_items=10,
        ... )
        >>> print(f"获取 {len(texts)} 条文本")
    """

    # 默认配额权重
    DEFAULT_WEIGHTS: dict[str, int] = {
        "research": 4,
        "irm": 3,
        "rating": 2,
        "news": 3,
        "announcement": 2,
        "cls": 2,
        "forecast": 3,  # #65 新增可达源（盈利预测一致预期）
    }

    # 数据源优先级（数值越大越靠前）
    SOURCE_PRIORITY: dict[str, int] = {
        "research": 4,
        "irm": 3,
        "rating": 2,
        "news": 1,
        "announcement": 1,
        "cls": 1,
    }

    # 各源在本部署网络下的可达性（#65）。host 静态分类：
    # datacenter.eastmoney / akshare 系可达；cninfo 系不可达；财联社挂起风险高归 uncertain。
    # irm 例外（市场相关）：沪市走上证 e互动（可达）、深市走巨潮 IRM（cninfo 不可达），见 _classify_reachability。
    SOURCE_REACHABILITY: dict[str, SourceReachability] = {
        "research": SourceReachability.REACHABLE,   # stock_research_report_em
        "news": SourceReachability.REACHABLE,       # stock_news_em
        "rating": SourceReachability.REACHABLE,     # stock_institute_recommend_detail
        "forecast": SourceReachability.REACHABLE,   # stock_profit_forecast_em（#65 新增源）
        "announcement": SourceReachability.UNREACHABLE,  # stock_zh_a_disclosure_report_cninfo
        "cls": SourceReachability.UNCERTAIN,        # 财联社（挂起风险高，有 30s 超时护栏）
    }

    # 素材过薄阈值（最终条数 < 此值时覆盖度元数据标降级）
    THIN_COVERAGE_THRESHOLD: int = 3

    # 标题相似度阈值（超过此值视为重复）
    TITLE_SIMILARITY_THRESHOLD: float = 0.8

    def __init__(
        self,
        config: AShareTextSourceConfig | None = None,
        logger: Logger | None = None,
    ):
        """
        初始化协调器

        Args:
            config: 文本数据源配置，包含启用的数据源和配额权重
            logger: 日志记录器
        """
        self._config = config or AShareTextSourceConfig()
        self._logger = logger or logging.getLogger("alice_test")

        # 初始化各数据源 fetcher
        self._news_fetcher = NewsFetcher()
        self._research_fetcher = ResearchFetcher()
        self._sse_irm_fetcher = SSEInteractiveFetcher()
        self._cninfo_irm_fetcher = CNInfoIRMFetcher()
        self._rating_fetcher = RatingChangeFetcher()
        self._announcement_fetcher = AnnouncementFetcher()  # #65/#66
        self._cls_fetcher = CLSNewsFetcher()  # #65/#66
        self._forecast_fetcher = ProfitForecastFetcher()  # #65 盈利预测一致预期

        # 统计信息
        self._fetch_stats: dict[str, dict[str, int]] = {
            "research": {"success": 0, "failure": 0},
            "irm": {"success": 0, "failure": 0},
            "rating": {"success": 0, "failure": 0},
            "news": {"success": 0, "failure": 0},
            "announcement": {"success": 0, "failure": 0},
            "cls": {"success": 0, "failure": 0},
            "forecast": {"success": 0, "failure": 0},
        }

        # 最近一次 fetch_texts 的素材覆盖度元数据（#65 / §五 #9），经 get_last_coverage() 取用
        self._last_coverage: TextCoverage | None = None

    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        整合获取所有文本数据

        流程：
        1. 计算各数据源配额
        2. 串行获取各数据源数据
        3. 合并、去重、排序
        4. 截断到 max_items

        Args:
            ticker: 股票代码，如 "601985.SH"
            name: 股票名称
            lookback_hours: 回溯时间窗口（小时）
            max_items: 最大返回条目数
            source_types: 可选的数据源类型过滤（忽略，使用配置）

        Returns:
            list[TextItem]: 聚合并处理后的文本列表
        """
        # 检查市场支持
        if not self.supports_market(ticker):
            self._logger.warning(f"[{ticker}] 非 A 股，AShareTextCoordinator 不支持")
            return []

        # #65/#66：A 股可在配置中设置更长回溯窗口（缓解 48h 太短、信息不足）
        if getattr(self._config, "lookback_hours", None):
            lookback_hours = self._config.lookback_hours

        self._logger.debug(
            f"[{ticker}] 开始获取文本数据, lookback={lookback_hours}h, max={max_items}"
        )

        all_items: list[TextItem] = []
        quotas = self._calculate_quotas(max_items)
        coverage_rows: list[TextSourceCoverage] = []

        self._logger.debug(f"[{ticker}] 配额分配: {quotas}")

        # 各源规格：(source_key, 显示名, fetcher)。research / news 走特殊接口（fetcher=None，
        # 由 _fetch_with_fallback 按 source_key 分派）；irm 按市场动态选择 fetcher。
        irm_fetcher = self._get_irm_fetcher(ticker)
        source_specs = [
            ("research", "研报", None),
            ("irm", self._get_irm_source_name(ticker), irm_fetcher),
            ("rating", "机构评级", self._rating_fetcher),
            ("news", "新闻", None),
            ("forecast", "盈利预测", self._forecast_fetcher),  # #65 新增可达源
            ("announcement", "公告", self._announcement_fetcher),  # #65/#66
            ("cls", "财联社", self._cls_fetcher),  # #65/#66
        ]
        for source_key, source_name, fetcher in source_specs:
            if not self._is_source_enabled(source_key):
                continue
            all_items.extend(
                self._collect(
                    source_key=source_key,
                    source_name=source_name,
                    fetcher=fetcher,
                    ticker=ticker,
                    name=name,
                    quota=quotas.get(source_key, 0),
                    lookback_hours=lookback_hours,
                    coverage_rows=coverage_rows,
                )
            )

        # 去重、排序、截断
        items = self._deduplicate(all_items)
        items = self._sort_by_relevance(items)
        final_items = items[:max_items]

        # #65 / §五 #9：记录素材覆盖度元数据（各源命中条数 + 总覆盖度 + 过薄降级标注）
        self._last_coverage = TextCoverage.build(
            ticker=ticker,
            per_source=coverage_rows,
            total_items=len(final_items),
            thin_threshold=self.THIN_COVERAGE_THRESHOLD,
        )

        cov = self._last_coverage
        msg = (
            f"[{ticker}] 聚合完成: 原始 {len(all_items)} 条, 去重后 {len(items)} 条, "
            f"最终 {len(final_items)} 条; 覆盖源 {cov.covered_sources or '无'}, "
            f"未覆盖 {cov.uncovered_sources or '无'}"
        )
        if cov.is_thin:
            self._logger.warning(f"{msg}; 素材过薄降级: {cov.thin_reason}")
        else:
            self._logger.info(msg)

        return final_items

    def _calculate_quotas(self, max_items: int) -> dict[str, int]:
        """
        根据配置权重计算各数据源配额

        Args:
            max_items: 总配额

        Returns:
            dict[str, int]: 各数据源的配额

        Example:
            weights = {"research": 4, "irm": 3, "rating": 2, "news": 3}
            max_items = 10

            total_weight = 12
            quotas = {
                "research": round(10 * 4/12) = 3,
                "irm": round(10 * 3/12) = 3,
                "rating": round(10 * 2/12) = 2,
                "news": round(10 * 3/12) = 2,
            }
        """
        weights = self._config.quota_weights
        enabled_sources = self._config.enabled_sources

        # 只考虑启用的数据源
        active_weights = {
            source: weights.get(source, self.DEFAULT_WEIGHTS.get(source, 1))
            for source in enabled_sources
        }

        if not active_weights:
            return {}

        total_weight = sum(active_weights.values())

        if total_weight == 0:
            # 平均分配
            base = max_items // len(active_weights)
            return {source: base for source in active_weights}

        # 按权重分配
        quotas: dict[str, int] = {}
        allocated = 0

        for source, weight in active_weights.items():
            quota = round(max_items * weight / total_weight)
            quotas[source] = quota
            allocated += quota

        # 处理舍入误差：把差值分给权重最高的
        diff = max_items - allocated
        if diff != 0:
            # 按权重排序
            sorted_sources = sorted(
                active_weights.keys(),
                key=lambda x: active_weights[x],
                reverse=True,
            )
            for i in range(abs(diff)):
                source = sorted_sources[i % len(sorted_sources)]
                if diff > 0:
                    quotas[source] += 1
                else:
                    if quotas[source] > 0:
                        quotas[source] -= 1

        return quotas

    def _is_source_enabled(self, source: str) -> bool:
        """
        检查数据源是否启用

        Args:
            source: 数据源名称 ("research", "irm", "rating", "news")

        Returns:
            bool: 是否启用
        """
        return source in self._config.enabled_sources

    def _get_irm_fetcher(self, ticker: str) -> TextProvider:
        """
        根据市场类型选择互动易数据源

        Args:
            ticker: 股票代码

        Returns:
            TextProvider: 对应的互动易 fetcher
                - .SH → SSEInteractiveFetcher
                - .SZ → CNInfoIRMFetcher
        """
        if ticker.upper().endswith(".SH"):
            return self._sse_irm_fetcher
        else:
            return self._cninfo_irm_fetcher

    def _get_irm_source_name(self, ticker: str) -> str:
        """
        获取互动易数据源名称

        Args:
            ticker: 股票代码

        Returns:
            str: 数据源名称
        """
        if ticker.upper().endswith(".SH"):
            return "上证e互动"
        else:
            return "巨潮互动易"

    def _classify_reachability(self, source_key: str, ticker: str) -> SourceReachability:
        """该源在本部署网络下的可达性（#65）。irm 按市场区分：沪市可达、深市(cninfo)不可达。"""
        if source_key == "irm":
            return (
                SourceReachability.REACHABLE
                if ticker.upper().endswith(".SH")
                else SourceReachability.UNREACHABLE
            )
        return self.SOURCE_REACHABILITY.get(source_key, SourceReachability.UNCERTAIN)

    def _skip_unreachable(self) -> bool:
        """是否对不可达源静默跳过（默认 True；可达网络的 P2 机器可在配置中关掉）。"""
        return getattr(self._config, "skip_unreachable_sources", True)

    def _collect(
        self,
        *,
        source_key: str,
        source_name: str,
        fetcher: TextProvider | None,
        ticker: str,
        name: str,
        quota: int,
        lookback_hours: int,
        coverage_rows: list[TextSourceCoverage],
    ) -> list[TextItem]:
        """对单个源做「可达性判定 → 抓取 → 记录覆盖度」，返回该源贡献的 items。

        - 配额为 0：不抓取，记 no_quota（不计为不可达）。
        - 不可达且开启跳过：静默跳过、记 skipped_unreachable（计入未覆盖），绝不阻塞其他源。
        - 否则正常抓取（_fetch_with_fallback 已吞异常优雅降级），记 ok/empty/failed + 命中条数。
        """
        reachability = self._classify_reachability(source_key, ticker)

        if quota <= 0:
            coverage_rows.append(
                TextSourceCoverage(
                    source=source_key, reachability=reachability,
                    attempted=False, hit_count=0, status="no_quota",
                )
            )
            return []

        if reachability == SourceReachability.UNREACHABLE and self._skip_unreachable():
            coverage_rows.append(
                TextSourceCoverage(
                    source=source_key, reachability=reachability,
                    attempted=False, hit_count=0, status="skipped_unreachable",
                )
            )
            self._logger.debug(
                f"[{ticker}] {source_name} 本网络不可达，静默跳过（计入未覆盖）"
            )
            return []

        fail_before = self._fetch_stats[source_key]["failure"]
        items = self._fetch_with_fallback(
            fetcher=fetcher, source_name=source_name, source_key=source_key,
            ticker=ticker, name=name, quota=quota, lookback_hours=lookback_hours,
        )
        failed = self._fetch_stats[source_key]["failure"] > fail_before
        status = "failed" if failed else ("ok" if items else "empty")
        coverage_rows.append(
            TextSourceCoverage(
                source=source_key, reachability=reachability,
                attempted=True, hit_count=len(items), status=status,
            )
        )
        return items

    def _fetch_with_fallback(
        self,
        fetcher: TextProvider | None,
        source_name: str,
        source_key: str,
        ticker: str,
        name: str,
        quota: int,
        lookback_hours: int,
    ) -> list[TextItem]:
        """
        带降级的数据获取

        Args:
            fetcher: 数据源 fetcher（研报和新闻需特殊处理，传 None）
            source_name: 数据源显示名称
            source_key: 数据源 key (用于统计)
            ticker: 股票代码
            name: 股票名称
            quota: 配额
            lookback_hours: 回溯时间

        Returns:
            list[TextItem]: 获取的文本列表，失败时返回空列表
        """
        if quota <= 0:
            return []

        try:
            if source_key == "research":
                # 研报使用特殊接口
                result = self._research_fetcher.fetch(
                    ticker=ticker,
                    symbol=self.extract_symbol(ticker),
                    name=name,
                    lookback_hours=lookback_hours,
                    max_items=quota,
                )
                items = result.items if result.success else []
            elif source_key == "news":
                # 新闻使用特殊接口
                result = self._news_fetcher.fetch(
                    ticker=ticker,
                    symbol=self.extract_symbol(ticker),
                    name=name,
                    lookback_hours=lookback_hours,
                    max_items=quota,
                )
                items = result.items if result.success else []
            elif fetcher is not None:
                # 其他数据源使用标准 fetch_texts 接口
                items = fetcher.fetch_texts(
                    ticker=ticker,
                    name=name,
                    lookback_hours=lookback_hours,
                    max_items=quota,
                )
            else:
                items = []

            self._fetch_stats[source_key]["success"] += 1
            self._logger.debug(
                f"[{ticker}] {source_name}: 获取 {len(items)}/{quota} 条"
            )
            return items

        except Exception as e:
            self._fetch_stats[source_key]["failure"] += 1
            self._logger.warning(f"[{ticker}] {source_name} 获取失败: {e}")
            return []

    def _deduplicate(self, items: list[TextItem]) -> list[TextItem]:
        """
        去重逻辑

        判断重复的标准：
        - 标题相似度 > 0.8
        - 或 summary 完全相同

        Args:
            items: 原始文本列表

        Returns:
            list[TextItem]: 去重后的列表
        """
        if not items:
            return []

        unique_items: list[TextItem] = []
        seen_summaries: set[str] = set()

        for item in items:
            # 检查 summary 完全相同
            summary_key = item.summary.strip()
            if summary_key in seen_summaries:
                continue

            # 检查标题相似度
            is_duplicate = False
            for existing in unique_items:
                similarity = self._calculate_title_similarity(
                    item.title, existing.title
                )
                if similarity > self.TITLE_SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_items.append(item)
                seen_summaries.add(summary_key)

        return unique_items

    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """
        计算两个标题的相似度

        Args:
            title1: 第一个标题
            title2: 第二个标题

        Returns:
            float: 相似度 (0.0 - 1.0)
        """
        # 规范化标题
        t1 = title1.strip().lower()
        t2 = title2.strip().lower()

        if not t1 or not t2:
            return 0.0

        return SequenceMatcher(None, t1, t2).ratio()

    def _sort_by_relevance(self, items: list[TextItem]) -> list[TextItem]:
        """
        按相关性排序

        排序因子：
        1. 数据类型优先级: research > irm > rating > news
        2. 时间新鲜度

        Args:
            items: 待排序的文本列表

        Returns:
            list[TextItem]: 排序后的列表
        """
        def sort_key(item: TextItem) -> tuple[int, float]:
            # 推断数据源类型
            source_type = self._infer_source_type(item)
            priority = self.SOURCE_PRIORITY.get(source_type, 0)
            # 时间戳取负数实现倒序（越新越靠前）
            timestamp = item.published_at.timestamp()
            return (-priority, -timestamp)

        return sorted(items, key=sort_key)

    def _infer_source_type(self, item: TextItem) -> str:
        """
        根据 TextItem 推断其数据源类型

        Args:
            item: 文本项

        Returns:
            str: 数据源类型 ("research", "irm", "rating", "news")
        """
        # 根据 source 和 title 特征判断
        source_lower = item.source.lower()

        # 互动易
        if "互动" in source_lower or "e互动" in source_lower:
            return "irm"

        # 评级变动（标题特征）
        if item.title.startswith(("[上调]", "[下调]", "[维持]", "[首次]")):
            return "rating"
        # 评级变动的 emoji 标识
        if item.title.startswith(("📈", "📉", "➡️", "🆕")):
            return "rating"

        # 投资者提问（互动易）
        if item.title.startswith("[投资者提问]"):
            return "irm"
        if item.title.startswith(("[已回复]", "[待回复]")):
            return "irm"

        # 研报
        if item.type == "research":
            # 如果是研报类型但有评级变动特征，归类为评级
            if "评级:" in item.summary or "变动:" in item.summary:
                return "rating"
            return "research"

        # 新闻
        return "news"

    def get_source_name(self) -> str:
        """获取数据源名称"""
        return "a_share_coordinator"

    def supports_market(self, ticker: str) -> bool:
        """
        判断是否支持该市场

        只支持 A 股（.SH 或 .SZ 后缀）

        Args:
            ticker: 证券代码

        Returns:
            bool: 是否支持
        """
        return self.detect_market(ticker) == "a_share"

    def get_supported_source_types(self) -> list[TextSourceType]:
        """返回支持的数据源类型"""
        return [
            TextSourceType.RESEARCH,
            TextSourceType.IRM,
            TextSourceType.RATING,
            TextSourceType.NEWS,
            TextSourceType.ANNOUNCEMENT,
            TextSourceType.CLS,
            TextSourceType.FORECAST,
        ]

    def get_fetch_stats(self) -> dict[str, dict[str, int]]:
        """
        获取各数据源的获取统计

        Returns:
            dict: 各数据源的成功/失败次数
        """
        return self._fetch_stats.copy()

    def get_last_coverage(self) -> TextCoverage | None:
        """获取最近一次 fetch_texts 的素材覆盖度元数据（#65 / §五 #9）。

        Returns:
            TextCoverage | None: 各源命中条数 + 总覆盖度 + 过薄降级标注；未跑过则为 None。
        """
        return self._last_coverage

    def reset_stats(self) -> None:
        """重置统计信息"""
        for source in self._fetch_stats:
            self._fetch_stats[source] = {"success": 0, "failure": 0}
