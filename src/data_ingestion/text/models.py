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
