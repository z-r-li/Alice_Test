"""
文本采集模块的数据模型定义

包含文本来源类型枚举和采集结果模型。
"""

from enum import Enum

from pydantic import BaseModel, Field

from ..models import TextItem


class TextSourceType(str, Enum):
    """
    文本来源类型枚举

    用于标识不同类型的文本数据来源。

    Attributes:
        NEWS: 新闻资讯
        RESEARCH: 研究报告
        IRM: 互动易问答 (Investor Relations Management)
        RATING: 机构评级变动
        WEB_SEARCH: 网络搜索结果
    """

    NEWS = "news"
    RESEARCH = "research"
    IRM = "irm"
    RATING = "rating"
    WEB_SEARCH = "web"
    ANNOUNCEMENT = "announcement"  # 公告（巨潮资讯），#65/#66 新增
    CLS = "cls"  # 财联社电报，#65/#66 新增
    FORECAST = "forecast"  # 机构盈利预测（东财），#65 新增——直接喂 implied_growth 素材


class SourceReachability(str, Enum):
    """文本数据源在本部署网络下的可达性分类（#65）

    依据 repo 已知网络事实静态分类：datacenter.eastmoney / akshare 系可达；
    sina / cninfo / push2his 系不可达；财联社等挂起风险高的归 uncertain（有超时护栏仍尝试）。
    供协调器降级策略使用：不可达源静默跳过并计入「未覆盖」。
    """

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNCERTAIN = "uncertain"


class TextSourceCoverage(BaseModel):
    """单个数据源在一次抓取中的覆盖情况（#65 / §五 #9）"""

    source: str = Field(..., description="数据源 key，如 research / irm / forecast")
    reachability: SourceReachability = Field(..., description="本网络可达性分类")
    attempted: bool = Field(default=False, description="是否真正发起了抓取")
    hit_count: int = Field(default=0, ge=0, description="该源命中（抓到）的条数")
    status: str = Field(
        default="",
        description="ok / empty / failed / skipped_unreachable / no_quota / disabled",
    )


class TextCoverage(BaseModel):
    """一次 fetch_texts 的素材覆盖度元数据（#65 / §五 #9）

    记录各源命中条数 + 总覆盖度，过薄时显式降级标注，供 S5 与报告判断共识可信度。
    """

    ticker: str = Field(default="", description="标的代码")
    per_source: list[TextSourceCoverage] = Field(
        default_factory=list, description="逐源覆盖情况"
    )
    total_items: int = Field(
        default=0, ge=0, description="聚合去重截断后的最终素材条数"
    )
    covered_sources: list[str] = Field(
        default_factory=list, description="命中条数 > 0 的源"
    )
    uncovered_sources: list[str] = Field(
        default_factory=list, description="跳过 / 失败 / 空 的源（未贡献素材）"
    )
    is_thin: bool = Field(default=False, description="最终素材是否过薄（< 阈值）")
    thin_threshold: int = Field(default=3, description="判定过薄的最终条数阈值")
    thin_reason: str | None = Field(
        default=None, description="过薄时的降级原因说明（供报告/S5）"
    )

    @classmethod
    def build(
        cls,
        ticker: str,
        per_source: list[TextSourceCoverage],
        total_items: int,
        thin_threshold: int = 3,
    ) -> "TextCoverage":
        """从逐源覆盖 + 最终条数构造覆盖度元数据（计算覆盖/未覆盖/过薄标注）。

        no_quota（启用但本次未分到配额、未发起抓取）不算「未覆盖」——它不是覆盖缺口，
        而是配额分配的产物；仍保留在 per_source 中供审查。
        """
        covered = [c.source for c in per_source if c.hit_count > 0]
        uncovered = [
            c.source for c in per_source
            if c.hit_count == 0 and c.status != "no_quota"
        ]
        is_thin = total_items < thin_threshold
        reason: str | None = None
        if is_thin:
            skipped = [c.source for c in per_source if c.status == "skipped_unreachable"]
            failed = [c.source for c in per_source if c.status == "failed"]
            parts = [f"最终素材仅 {total_items} 条（阈值 {thin_threshold}）"]
            if not covered:
                parts.append("无任何源命中")
            if skipped:
                parts.append(f"不可达跳过: {', '.join(skipped)}")
            if failed:
                parts.append(f"抓取失败: {', '.join(failed)}")
            reason = "；".join(parts)
        return cls(
            ticker=ticker,
            per_source=per_source,
            total_items=total_items,
            covered_sources=covered,
            uncovered_sources=uncovered,
            is_thin=is_thin,
            thin_threshold=thin_threshold,
            thin_reason=reason,
        )


class FetchResult(BaseModel):
    """
    单个 Fetcher 的采集结果

    封装了文本采集操作的返回结果，包含采集的数据项、
    状态信息和统计数据。

    Attributes:
        items: 采集到的文本数据列表
        source_type: 文本来源类型
        success: 采集是否成功
        error_message: 错误信息（采集失败时）
        fetch_count: 实际获取的条数
        request_count: 请求的条数

    Example:
        >>> result = FetchResult(
        ...     items=[text_item1, text_item2],
        ...     source_type=TextSourceType.NEWS,
        ...     success=True,
        ...     fetch_count=2,
        ...     request_count=10
        ... )
    """

    items: list[TextItem] = Field(default_factory=list, description="采集到的文本数据列表")
    source_type: TextSourceType = Field(..., description="文本来源类型")
    success: bool = Field(default=True, description="采集是否成功")
    error_message: str | None = Field(default=None, description="错误信息")
    fetch_count: int = Field(default=0, ge=0, description="实际获取的条数")
    request_count: int = Field(default=0, ge=0, description="请求的条数")

    def model_post_init(self, __context) -> None:
        """自动计算 fetch_count（如果未显式设置）"""
        if self.fetch_count == 0 and self.items:
            object.__setattr__(self, "fetch_count", len(self.items))
