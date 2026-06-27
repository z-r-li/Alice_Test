"""
Module A: 市场共识引擎

职责：
- 调用 LLM 分析市场文本 + 估值数据
- 提取市场情绪评分、隐含增长率、关键叙事
"""
import logging

from ..data_ingestion.models import TickerRawData, TextItem
from ..llm import DeepSeekClient, ConsensusResult
from ..utils.sanitizer import TextSanitizer, get_sanitizer


class InsufficientDataError(Exception):
    """文本数据不足以做可信的市场共识分析。

    C2 fail-closed：无有效文本摘要时拒绝以「暂无相关资讯」占位符调用 LLM，否则模型会凭空
    反推 sentiment / implied_growth，被伪装成一次可计算审计、污染脊柱。由调用方捕获后标
    status=data_partial + needs_due_diligence，不进正常 alpha/IC 样本。
    """


class ConsensusEngine:
    """市场共识引擎 (Module A)"""

    def __init__(
        self,
        llm_client: DeepSeekClient,
        sanitizer: TextSanitizer | None = None,
    ):
        """
        初始化市场共识引擎

        Args:
            llm_client: DeepSeek 客户端实例
            sanitizer: 文本脱敏器实例（可选，默认使用全局单例）
        """
        self._llm_client = llm_client
        self._sanitizer = sanitizer or get_sanitizer()
        self._logger = logging.getLogger("alice_test")

    def analyze(self, raw_data: TickerRawData) -> ConsensusResult:
        """
        分析市场共识

        Args:
            raw_data: 标的原始数据（包含行情和文本）

        Returns:
            ConsensusResult: 包含 sentiment_score, implied_growth, key_narrative

        Raises:
            InsufficientDataError: 无有效文本摘要（fail-closed，不以占位符调用 LLM）
            EngineError: 分析失败
        """
        # C2 fail-closed：先校验有效文本，无则抛错，绝不以占位符喂 LLM 反推增长率。
        valid_texts = [t for t in raw_data.texts if t.summary and t.summary.strip()]
        if not valid_texts:
            raise InsufficientDataError(
                f"[{raw_data.ticker}] 无有效文本摘要，fail-closed 拒绝调用市场共识 LLM"
            )
        texts_content = self._format_texts(valid_texts, raw_data.ticker)

        # 对发送给 LLM 的文本进行脱敏处理
        safe_name = self._sanitizer.sanitize(raw_data.name)
        safe_texts = self._sanitizer.sanitize(texts_content)

        self._logger.debug(
            f"[{raw_data.ticker}] 调用 LLM 进行市场共识分析，"
            f"文本数量: {len(raw_data.texts)}"
        )

        return self._llm_client.get_consensus(
            ticker=raw_data.ticker,
            ticker_name=safe_name,
            price_close=raw_data.quote.price_close,
            pe_ttm=raw_data.quote.pe_ttm,
            pb=raw_data.quote.pb,
            texts_content=safe_texts,
        )

    def _format_texts(self, texts: list[TextItem], ticker: str = "") -> str:
        """
        格式化（已由 analyze 过滤的有效）文本列表为 LLM 输入格式

        Args:
            texts: 已过滤的有效文本项列表（summary 非空）
            ticker: 标的代码（用于日志）

        Returns:
            str: 格式化后的文本内容
        """
        formatted = []
        for i, text in enumerate(texts, 1):
            formatted.append(
                f"{i}. [{text.source}] ({text.type}) {text.title}\n"
                f"   摘要: {text.summary}"
            )

        self._logger.debug(
            f"[{ticker}] 格式化 {len(texts)} 条文本用于 LLM 分析"
        )
        return "\n\n".join(formatted)
