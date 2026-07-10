"""
Gap 计算器与审计信号判定

职责：
- 计算认知差 Gap = Our_Growth - Market_Implied_Growth
- 根据 Gap（α 差）双向生成审计信号（信号语义 v2）
- sentiment 不参与信号判定，仅产 sentiment_overheat 过热 flag 供 S6 风控 overlay 登记

信号语义 v2（D-20260627-P0-1 / D-20260627-CDX-1 / D-20260705-1）：
- OPPORTUNITY = 正 α（gap > opportunity_gap_min）：市场定价低于我方 thesis 模型
- OVERHEATED  = 负 α（gap < -overheated_gap_min）：市场 implied 定价高于我方 thesis 模型
- v1「gap+sentiment 双条件」判定式已废止（自相矛盾，见 D-20260627-P0-1）
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

    # 信号语义 v2：情绪过热 flag（sentiment_score > overheated_sentiment_min）。
    # 只登记、不参与信号判定，由 S6 追加 "SENTIMENT_OVERHEAT" 进 correlation_flags；
    # 权重折减系数未拍，本期不做折减（向后兼容默认 False）。
    sentiment_overheat: bool = False

    # 状态
    # PR-A fail-closed：扩充 data_partial（缺有效文本）/ pipeline_error（流水线整体回退）；
    # 非 "ok" 即「不进正常 alpha/IC 样本」。向后兼容（旧产物默认 "ok"）。
    status: Literal[
        "ok", "data_error", "llm_error", "data_partial", "pipeline_error", "unknown"
    ] = "ok"
    # 缺数据 / 失败路径的 fail-closed 标记：True 表示该行需人工尽调、不得进入正常 alpha/IC 样本
    # （向后兼容扩展，默认 False；旧 CSV 读回缺列时为 None，表示未知）。
    needs_due_diligence: bool | None = False

    # P1: 多阶段流水线产物引用（向后兼容扩展，默认 None）
    artifact_dir: str | None = None  # S1–S5 产物 JSON 目录
    evidence_summary: str | None = None  # 证据链 / 尽调队列一句话摘要

    # S6: 组合层风控回填字段（RiskEngine；向后兼容扩展，默认 None）
    suggested_weight: float | None = None  # 建议仓位（~ref_weight 软参考、非硬顶）
    correlation_flags: list[str] | None = None  # 同簇/高相关 ticker + SENTIMENT_OVERHEAT 哨兵（非 ticker）
    structural_exit: list[str] | None = None  # 结构性退出触发（来自 S1 kill_criteria）
    quant_exit_target: float | None = None  # 量化退出目标价 / 估值（D3 待定，v0.1 留空）
    risk_adjusted_action: str | None = None  # 叠加风控后动作 BUY / TRIM / WAIT / EXIT / AVOID
    risk_contribution: float | None = None  # 对组合总风险的贡献（v0.2 接相关阵后算）

    # 100Step 借鉴 PR②：证据链完成度四计数（审计指标，按 S3 enforce 之后的
    # PipelineResult.chain.links 计；向后兼容扩展，默认 None）。None = 没走到证据链
    # （fail-closed / 流水线回退 / pipeline 关闭），0 = 拆了链但该计数为空——语义
    # 不同，绝不以 0 顶替 None。
    cov_links_total: int | None = None  # links 总数
    cov_links_quant: int | None = None  # 引擎可验证环节数（proxy_type == quantitative）
    cov_links_evidenced: int | None = None  # 已挂证据环节数（evidence is not None）
    cov_links_dd: int | None = None  # 尽调环节数（due_diligence 或 evidence.needs_due_diligence，去重）


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

    def determine_signal(self, gap: float) -> AuditSignal:
        """
        根据 Gap（α 差）判定审计信号（信号语义 v2，纯 α 差双向触发）

        判定逻辑（D-20260627-P0-1 / D-20260705-1）：
        - gap > opportunity_gap_min → OPPORTUNITY（正 α）
        - gap < -overheated_gap_min → OVERHEATED（负 α；动作空间 = 不进场/减仓/清仓，
          不做空——SHORT 为远期规划，2026-07-08 澄清，届时另拍）
        - 其他 → WAIT；gap 为 NaN（fail-closed 行）时所有比较为 False → WAIT

        sentiment 已摘出信号门，不参与判定（v1 判定式废止）；情绪过热单列为
        sentiment_overheat flag（见 is_sentiment_overheat）。

        Args:
            gap: 认知差（our_growth − implied_growth）

        Returns:
            AuditSignal: 审计信号
        """
        if gap > self._thresholds.opportunity_gap_min:
            return AuditSignal.OPPORTUNITY

        if gap < -self._thresholds.overheated_gap_min:
            return AuditSignal.OVERHEATED

        return AuditSignal.WAIT

    def is_sentiment_overheat(self, sentiment_score: int) -> bool:
        """情绪过热 flag 判定（sentiment_score > overheated_sentiment_min，阈值沿用 80）。

        与信号判定解耦：只登记 flag 给 S6 风控 overlay（CDX-1「sentiment 不单独产 α、
        不纯做 veto」），本期不做权重折减（折减系数未拍）。
        """
        return sentiment_score > self._thresholds.overheated_sentiment_min

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

        signal = self.determine_signal(gap=gap)

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
            sentiment_overheat=self.is_sentiment_overheat(consensus.sentiment_score),
        )
