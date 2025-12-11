"""
Module A: 市场共识引擎

职责：
- 调用 LLM 分析市场文本 + 估值数据
- 提取市场情绪评分、隐含增长率、关键叙事
"""
from ..data_ingestion.models import TickerRawData, TextItem
from ..llm import DeepSeekClient, ConsensusResult


class ConsensusEngine:
    """市场共识引擎 (Module A)"""

    def __init__(self, llm_client: DeepSeekClient):
        """
        初始化市场共识引擎

        Args:
            llm_client: DeepSeek 客户端实例
        """
        self._llm_client = llm_client

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
        texts_content = self._format_texts(raw_data.texts)

        return self._llm_client.get_consensus(
            ticker=raw_data.ticker,
            ticker_name=raw_data.name,
            price_close=raw_data.quote.price_close,
            pe_ttm=raw_data.quote.pe_ttm,
            pb=raw_data.quote.pb,
            texts_content=texts_content,
        )

    def _format_texts(self, texts: list[TextItem]) -> str:
        """
        格式化文本列表为 LLM 输入格式

        Args:
            texts: 文本项列表

        Returns:
            str: 格式化后的文本内容
        """
        if not texts:
            return "暂无相关资讯"

        formatted = []
        for i, text in enumerate(texts, 1):
            formatted.append(
                f"{i}. [{text.source}] ({text.type}) {text.title}\n"
                f"   摘要: {text.summary}"
            )
        return "\n\n".join(formatted)
