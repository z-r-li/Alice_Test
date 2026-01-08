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
            EngineError: 分析失败
        """
        texts_content = self._format_texts(raw_data.texts, raw_data.ticker)

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
        格式化文本列表为 LLM 输入格式

        Args:
            texts: 文本项列表
            ticker: 标的代码（用于日志）

        Returns:
            str: 格式化后的文本内容
        """
        if not texts:
            self._logger.warning(
                f"[{ticker}] 无有效文本数据，使用占位符"
            )
            return "暂无相关资讯"

        # 过滤掉空摘要的文本
        valid_texts = [t for t in texts if t.summary and t.summary.strip()]
        if not valid_texts:
            self._logger.warning(
                f"[{ticker}] 所有文本摘要为空，使用占位符"
            )
            return "暂无相关资讯"

        formatted = []
        for i, text in enumerate(valid_texts, 1):
            formatted.append(
                f"{i}. [{text.source}] ({text.type}) {text.title}\n"
                f"   摘要: {text.summary}"
            )

        self._logger.debug(
            f"[{ticker}] 格式化 {len(valid_texts)} 条文本用于 LLM 分析"
        )
        return "\n\n".join(formatted)
