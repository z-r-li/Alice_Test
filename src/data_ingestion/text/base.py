"""
文本数据提供者抽象基类
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Literal

from ..models import TextItem
from .models import TextSourceType

logger = logging.getLogger("alice_test")

# A 股各源站的墙上时间口径（北京时）。中国 1991 年后无夏令时，固定 +08:00 即精确值。
CHINA_TZ = timezone(timedelta(hours=8))

# drop_future_items(source_tz=) 的「未显式指定」哨兵：与显式传 None（= 按部署机本地解释）
# 区分开，好让默认值能按 ticker 推断源时区 —— 默认必须是安全的那一个。
_INFER_FROM_TICKER: Any = object()


class TextProvider(ABC):
    """文本数据提供者抽象基类"""

    @abstractmethod
    def fetch_texts(
        self,
        ticker: str,
        name: str,
        lookback_hours: int = 48,
        max_items: int = 10,
        source_types: list[TextSourceType] | None = None,
    ) -> list[TextItem]:
        """
        获取指定标的的相关文本数据

        Args:
            ticker: 证券代码
            name: 标的名称（用于搜索）
            lookback_hours: 回溯时间窗口（小时），默认 48 小时
            max_items: 最大返回条数，默认 10 条
            source_types: 可选的数据源类型过滤列表，为 None 时返回所有类型

        Returns:
            list[TextItem]: 文本数据列表，按相关性/时间排序
        """
        ...

    @abstractmethod
    def get_source_name(self) -> str:
        """
        获取数据源名称

        Returns:
            str: 如 "中信证券"、"东方财富" 等
        """
        ...

    @abstractmethod
    def supports_market(self, ticker: str) -> bool:
        """
        判断该 Provider 是否支持指定市场的 ticker

        Args:
            ticker: 证券代码，如 "601985.SH"、"0700.HK"、"AAPL"

        Returns:
            bool: 是否支持该市场
        """
        ...

    @abstractmethod
    def get_supported_source_types(self) -> list[TextSourceType]:
        """
        返回该 Provider 支持的所有数据源类型

        Returns:
            list[TextSourceType]: 支持的数据源类型列表
        """
        ...

    def _get_time_window(self, lookback_hours: int) -> tuple[datetime, datetime]:
        """
        计算时间窗口

        Args:
            lookback_hours: 回溯小时数

        Returns:
            tuple[datetime, datetime]: (start_time, end_time)
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=lookback_hours)
        return start_time, end_time

    @staticmethod
    def source_tz_for_market(ticker: str) -> tzinfo | None:
        """该市场的 fetcher 给 **naive** ``published_at`` 用的是哪个时区的墙上时间。

        A 股各 fetcher 一律 ``datetime.strptime(<源站字符串>, ...)``，得到的 naive 值是
        **北京墙上时间**（源站口径），而非部署机本地时间 —— 见 ``news_fetcher._parse_datetime``、
        ``rating_fetcher``、``research_fetcher``、``sse_interactive_fetcher``、
        ``cninfo_irm_fetcher``、``announcement_fetcher``。若拿本地 naive ``datetime.now()``
        直接比它，在非 UTC+8 部署上「最近 offset 小时内发布」的条目会被整批误判成未来戳
        （UTC-4 上即最近 12 小时的最新素材全丢）。

        返回 ``None`` = 「按部署机本地时区解释」，用于 MockTextProvider 这类本身就用本地
        ``datetime.now()`` 盖戳的源；HK/US 直接产出 aware UTC，不走 naive 分支。

        用固定 +08:00 而非 ``ZoneInfo("Asia/Shanghai")``：中国 1991 年后无夏令时，固定偏移
        即精确值，且不依赖 Windows 上需额外安装的 ``tzdata``。
        """
        return CHINA_TZ if TextProvider.detect_market(ticker) == "a_share" else None

    @staticmethod
    def _local_tz() -> tzinfo:
        """部署机**当前**的 UTC 偏移（固定 offset 形式）。

        故意只取一次「现在」的偏移，而不对每个条目调 ``datetime.astimezone()``：
        Windows 上对 1970 年前或超出平台可表示范围的 **naive** 值，``astimezone()`` 会抛
        ``OSError: [Errno 22]``（实测 ``datetime(1970, 1, 1).astimezone()`` 即抛），而护栏
        必须「不 fail 整跑」—— 一条畸形戳不该掀掉整个标的的文本。
        代价：跨夏令时的历史条目按当前偏移解释，最坏差 1 小时；条目本就落在回溯窗内，
        且该误差远小于「抛错丢光全部素材」。
        """
        return datetime.now().astimezone().tzinfo      # 「现在」恒可转换，不会抛

    @staticmethod
    def _to_instant(moment: datetime, assume_tz: tzinfo) -> datetime:
        """把 datetime 归一成 **aware 绝对时刻**，供跨时区比较。

        - aware：原样返回（已是绝对时刻）。
        - naive：按 ``assume_tz`` 解释（纯 ``replace``，不触平台 localtime，不会抛）。

        比较绝对时刻而非墙上时间，顺带消除夏令时回拨那一小时的歧义 —— 归一成本地 naive
        再比会在该小时内把「45 分钟前发布」判成未来。
        """
        if moment.tzinfo is not None:
            return moment
        return moment.replace(tzinfo=assume_tz)

    @classmethod
    def drop_future_items(
        cls,
        items: list[TextItem],
        ticker: str,
        now: datetime | None = None,
        source_tz: tzinfo | None = _INFER_FROM_TICKER,
    ) -> list[TextItem]:
        """特征窗**上界**护栏：丢弃 ``published_at`` 晚于 ``now`` 的未来戳文本。

        各 fetcher 的时间过滤只有下界（``published_at < cutoff → continue``，只挡太旧、
        零上界）。源时钟偏移或日期解析错（如年份 typo 成 2027）产生的未来戳条目会直接进入
        S2/S3 的 LLM 上下文，构成 look-ahead 泄露。本方法是**聚合口**的统一上界护栏，
        一处覆盖其下所有 provider / fetcher，无需逐个改 fetcher。

        闭边界：``published_at <= now`` 保留，仅 ``> now`` 丢弃。

        比较在**绝对时刻**上进行：naive 戳按 ``source_tz``（A 股 = 北京时，见
        ``source_tz_for_market``）解释，aware 戳原样。故护栏与部署机时区无关 —— 这是必须的，
        naive 戳的时区语义由**源站**决定而非部署机，直接拿本地 now 比会在非 UTC+8 主机上
        整批误杀最新素材。

        丢弃必留 WARNING（含条数与 ticker），绝不静默；但**不 fail 整跑**——拒收可疑数据
        ≠ 编造数据（与 PR-A「不编造 / fail-closed」纪律相容），而个别源的异常戳不应杀掉
        整个标的（与各 fetcher 的 fail-open 降级一致）。

        Args:
            items: 待过滤的文本列表
            ticker: 证券代码；用于日志定位，并在 ``source_tz`` 未显式指定时推断源时区
            now: 上界时刻，默认当前时刻；naive 值按部署机本地时区解释
            source_tz: naive ``published_at`` 的源时区。**默认按 ticker 推断**
                （``source_tz_for_market``），使默认行为即安全行为；显式传 ``None``
                表示「按部署机本地解释」，仅用于本身就用本地 ``datetime.now()``
                盖戳的源（如 MockTextProvider）。

        Returns:
            list[TextItem]: 剔除未来戳后的列表，保持原有顺序

        Example:
            >>> TextProvider.drop_future_items(items, "601985.SH")   # doctest: +SKIP
        """
        if source_tz is _INFER_FROM_TICKER:
            source_tz = cls.source_tz_for_market(ticker)
        local_tz = cls._local_tz()
        # naive published_at 的解释时区：源站时区（A 股 = 北京）优先，否则按部署机本地
        assume_tz = source_tz if source_tz is not None else local_tz
        cutoff = (
            datetime.now(timezone.utc) if now is None else cls._to_instant(now, local_tz)
        )

        kept: list[TextItem] = []
        dropped: list[TextItem] = []
        for item in items:
            published_at = cls._to_instant(item.published_at, assume_tz)
            target = kept if published_at <= cutoff else dropped
            target.append(item)

        if dropped:
            # 日志显式带上界的时区与 naive 戳的解释口径：否则「上界 02:16 UTC」与条目
            # 「10:11（北京）」并列会看着像误杀，排查时无从判断是数据问题还是护栏问题。
            tz_label = str(source_tz) if source_tz is not None else "部署机本地时区"
            detail = "; ".join(
                f"{item.source}|{item.published_at}|{item.title[:40]}" for item in dropped
            )
            logger.warning(
                f"[{ticker}] 丢弃 {len(dropped)} 条未来戳文本（上界 "
                f"{cutoff:%Y-%m-%d %H:%M:%S%z}，naive 戳按 {tz_label} 解释；"
                f"疑似源时钟偏移 / 日期解析错）: {detail}"
            )

        return kept

    @staticmethod
    def extract_symbol(ticker: str) -> str:
        """
        从 ticker 中提取纯代码（去除市场后缀）

        Args:
            ticker: 证券代码，如 "601985.SH"、"000001.SZ"、"0700.HK"、"AAPL"

        Returns:
            str: 纯代码部分

        Examples:
            >>> TextProvider.extract_symbol("601985.SH")
            '601985'
            >>> TextProvider.extract_symbol("000001.SZ")
            '000001'
            >>> TextProvider.extract_symbol("0700.HK")
            '0700'
            >>> TextProvider.extract_symbol("AAPL")
            'AAPL'
        """
        if "." in ticker:
            return ticker.split(".")[0]
        return ticker

    @staticmethod
    def detect_market(ticker: str) -> Literal["a_share", "hk", "us"]:
        """
        根据 ticker 后缀判断市场类型

        Args:
            ticker: 证券代码，如 "601985.SH"、"000001.SZ"、"0700.HK"、"AAPL"

        Returns:
            Literal["a_share", "hk", "us"]: 市场类型
                - "a_share": A 股（.SH 或 .SZ 后缀）
                - "hk": 港股（.HK 后缀）
                - "us": 美股（无后缀或其他）

        Examples:
            >>> TextProvider.detect_market("601985.SH")
            'a_share'
            >>> TextProvider.detect_market("000001.SZ")
            'a_share'
            >>> TextProvider.detect_market("0700.HK")
            'hk'
            >>> TextProvider.detect_market("AAPL")
            'us'
        """
        ticker_upper = ticker.upper()
        if ticker_upper.endswith(".SH") or ticker_upper.endswith(".SZ"):
            return "a_share"
        elif ticker_upper.endswith(".HK"):
            return "hk"
        else:
            return "us"
