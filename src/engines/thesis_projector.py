"""
Module B: 信念投影器

职责：
- 调用 LLM 基于用户宏观信念评估合理增长率
- 路径独立于市场情绪
"""
from ..config.models import TargetConfig
from ..llm import DeepSeekClient, ThesisProjectionResult
from ..utils.sanitizer import TextSanitizer, get_sanitizer


class ThesisProjector:
    """信念投影器 (Module B)"""

    def __init__(
        self,
        llm_client: DeepSeekClient,
        sanitizer: TextSanitizer | None = None,
    ):
        """
        初始化信念投影器

        Args:
            llm_client: DeepSeek 客户端实例
            sanitizer: 文本脱敏器实例（可选，默认使用全局单例）
        """
        self._llm_client = llm_client
        self._sanitizer = sanitizer or get_sanitizer()

    def project(
        self,
        target: TargetConfig,
        industry: str = "未知",
    ) -> ThesisProjectionResult:
        """
        基于用户信念投影合理增长率

        Args:
            target: 标的配置（包含 ticker, name, thesis）
            industry: 行业信息（可选）

        Returns:
            ThesisProjectionResult: 包含 our_growth, reasoning

        Raises:
            EngineError: 投影失败
        """
        # 对发送给 LLM 的文本进行脱敏处理
        safe_name = self._sanitizer.sanitize(target.name)
        safe_thesis = self._sanitizer.sanitize(target.thesis)
        safe_industry = self._sanitizer.sanitize(industry)

        return self._llm_client.get_thesis_projection(
            ticker=target.ticker,
            ticker_name=safe_name,
            user_thesis=safe_thesis,
            industry=safe_industry,
        )

    def project_batch(
        self,
        targets: list[TargetConfig],
    ) -> dict[str, ThesisProjectionResult]:
        """
        批量投影多个标的

        Args:
            targets: 标的配置列表

        Returns:
            dict[str, ThesisProjectionResult]: ticker -> 投影结果 的映射
        """
        results = {}
        for target in targets:
            try:
                results[target.ticker] = self.project(target)
            except Exception as e:
                # 记录错误，继续处理其他标的
                # TODO: 使用 logger 记录
                pass
        return results
