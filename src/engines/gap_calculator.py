"""
Gap 计算器与审计信号判定

职责：
- 计算认知差 Gap = Our_Growth - Market_Implied_Growth
- 根据 Gap 和情绪评分生成审计信号
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

from ..llm.models import ConsensusResult, ThesisProjectionResult
from ..config.models import GapThresholdConfig


class AuditSignal(str, Enum):
    """审计信号枚举"""
    OPPORTUNITY = "OPPORTUNITY"  # 机会
    OVERHEATED = "OVERHEATED"  # 过热
    WAIT = "WAIT"  # 观望


@dataclass
class AuditResult:
    """
    单个标的的审计结果

    对应 PRD 6.1 节 audit_report.csv 字段定义
    """
    # 基础信息
    date: datetime  # 审计日期 (YYYY-MM-DD)
    ticker: str  # 股票代码
    name: str  # 公司名称
    price: float  # 收盘价
    pe_ttm: float | None  # 市盈率（TTM）

    # Module A 输出
    sentiment_score: int  # 情绪分数 (0-100)
    sentiment_label: str  # 情绪标签 (恐慌|悲观|中性|乐观|狂热)
    implied_growth: float  # 市场隐含增长率 %
    key_narrative: str  # 一句话市场总结
    key_worry: str  # 主要担忧
    key_hope: str  # 主要期待

    # Module B 输出
    thesis_aligned: bool  # 是否与投资信念一致
    our_growth: float  # 信念预期增长率 %
    confidence: str  # 预测置信度 (高|中|低)
    reasoning: str  # 信念投影推理说明

    # 信号判定
    gap: float  # 认知差 (our - implied)
    signal: AuditSignal  # OPPORTUNITY / OVERHEATED / WAIT

    # 状态
    status: Literal["ok", "data_error", "llm_error"] = "ok"


class GapCalculator:
    """Gap 计算器与信号判定"""

    def __init__(self, thresholds: GapThresholdConfig | None = None):
        """
        初始化 Gap 计算器

        Args:
            thresholds: 判定阈值配置，默认使用 PRD 中的标准值
        """
        self._thresholds = thresholds or GapThresholdConfig()

    def calculate_gap(
        self,
        our_growth: float,
        implied_growth: float,
    ) -> float:
        """
        计算认知差

        Args:
            our_growth: 我们预期的增长率
            implied_growth: 市场隐含增长率

        Returns:
            float: Gap = Our_Growth - Implied_Growth
        """
        return our_growth - implied_growth

    def determine_signal(
        self,
        gap: float,
        sentiment_score: int,
    ) -> AuditSignal:
        """
        根据 Gap 和情绪评分判定审计信号

        判定逻辑（来自 PRD 5.5）：
        - Gap > 10 且 Sentiment < 40 → OPPORTUNITY
        - Sentiment > 80 → OVERHEATED
        - 其他 → WAIT

        Args:
            gap: 认知差
            sentiment_score: 情绪评分

        Returns:
            AuditSignal: 审计信号
        """
        if (
            gap > self._thresholds.opportunity_gap_min
            and sentiment_score < self._thresholds.opportunity_sentiment_max
        ):
            return AuditSignal.OPPORTUNITY

        if sentiment_score > self._thresholds.overheated_sentiment_min:
            return AuditSignal.OVERHEATED

        return AuditSignal.WAIT

    def compute_audit_result(
        self,
        ticker: str,
        name: str,
        price: float,
        pe_ttm: float | None,
        consensus: ConsensusResult,
        thesis_projection: ThesisProjectionResult,
        audit_date: datetime | None = None,
    ) -> AuditResult:
        """
        计算完整审计结果

        Args:
            ticker: 证券代码
            name: 标的名称
            price: 收盘价
            pe_ttm: 市盈率（TTM）
            consensus: Module A 输出
            thesis_projection: Module B 输出
            audit_date: 审计日期，默认为当天

        Returns:
            AuditResult: 完整审计结果
        """
        gap = self.calculate_gap(
            our_growth=thesis_projection.our_growth,
            implied_growth=consensus.implied_growth,
        )

        signal = self.determine_signal(
            gap=gap,
            sentiment_score=consensus.sentiment_score,
        )

        return AuditResult(
            date=audit_date or datetime.now(),
            ticker=ticker,
            name=name,
            price=price,
            pe_ttm=pe_ttm,
            sentiment_score=consensus.sentiment_score,
            sentiment_label=consensus.sentiment_label,
            implied_growth=consensus.implied_growth,
            key_narrative=consensus.key_narrative,
            key_worry=consensus.key_worry,
            key_hope=consensus.key_hope,
            thesis_aligned=thesis_projection.thesis_aligned,
            our_growth=thesis_projection.our_growth,
            confidence=thesis_projection.confidence,
            reasoning=thesis_projection.reasoning,
            gap=gap,
            signal=signal,
        )
