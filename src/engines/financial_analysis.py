"""
S4 财务分析引擎 (FinancialAnalysisEngine)

「技术面 / 财报分析」就活在这一阶段（改进计划 §2 Stage 4）。摄入财务报表，
计算 forward PE / PEG / 收入·毛利·现金流趋势，产出可追溯的 `Evidence`。

护栏（AGENT.md §7）：
- `Evidence.data` 只放本地抓取/计算的真实数字；缺数据标 needs_due_diligence，绝不编造。
- forward PE 优先用 provider 前瞻值（yfinance）；A 股无前瞻数据时，按「给定增长 / 历史盈利
  CAGR」推导并显式标注 basis，无法推导则标 unavailable + 需尽调。
- 纯计算 + 规则判断，无 LLM 调用 → 可完全离线测试（定量 link 的证据由本引擎产出，
  定性 link 的证据由 LLM 在流水线中产出）。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from ..data_ingestion.financials import (
    FinancialReport,
    FinancialsFetchError,
    FinancialsProvider,
)
from ..llm.models import Evidence


@dataclass
class FinancialMetrics:
    """S4 计算输出：财务指标与趋势"""

    ticker: str
    currency: str | None = None
    periods_used: int = 0
    trailing_pe: float | None = None
    forward_pe: float | None = None
    forward_pe_basis: str = "unavailable"  # provider/derived_from_growth/derived_from_history/unavailable
    peg_ratio: float | None = None
    revenue_latest: float | None = None
    revenue_yoy: float | None = None  # %
    revenue_cagr: float | None = None  # %
    earnings_cagr: float | None = None  # %
    gross_margin_latest: float | None = None  # %
    net_margin_latest: float | None = None  # %
    revenue_trend: str = "unknown"
    gross_margin_trend: str = "unknown"
    net_margin_trend: str = "unknown"
    ocf_trend: str = "unknown"
    ocf_latest_positive: bool | None = None
    notes: list[str] = field(default_factory=list)
    status: str = "ok"  # ok / partial / data_error


def _cagr_pct(first: float | None, last: float | None, years: int) -> float | None:
    """复合年增长率 (%)；要求首末同号为正且 years>0"""
    if first is None or last is None or years <= 0:
        return None
    if first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def _trend_value(first: float | None, last: float | None, rel: float = 0.05) -> str:
    """绝对额趋势（营收 / 现金流）"""
    if first is None or last is None or first == 0:
        return "unknown"
    change = (last - first) / abs(first)
    if change > rel:
        return "improving"
    if change < -rel:
        return "declining"
    return "stable"


def _trend_points(first: float | None, last: float | None, pp: float = 1.0) -> str:
    """百分点趋势（毛利率 / 净利率）"""
    if first is None or last is None:
        return "unknown"
    diff = last - first
    if diff > pp:
        return "improving"
    if diff < -pp:
        return "declining"
    return "stable"


class FinancialAnalysisEngine:
    """S4 财务分析引擎"""

    def __init__(self, provider: FinancialsProvider | None = None):
        """
        Args:
            provider: 财报数据提供者；analyze_report() 不依赖它，
                      analyze_ticker() 需要它来抓取报表。
        """
        self._provider = provider
        self._logger = logging.getLogger("alice_test")

    # ---- 抓取 + 分析 ----

    def analyze_ticker(
        self,
        ticker: str,
        trailing_pe: float | None = None,
        expected_growth_pct: float | None = None,
        max_periods: int = 5,
    ) -> FinancialMetrics:
        """抓取财报并分析。抓取失败不抛出，返回 data_error 指标（标注需尽调）。"""
        if self._provider is None:
            raise ValueError("FinancialAnalysisEngine 未配置 provider，无法 analyze_ticker")
        try:
            report = self._provider.get_financials(ticker, max_periods=max_periods)
        except FinancialsFetchError as e:
            self._logger.warning(f"[{ticker}] 财报获取失败: {e}")
            return FinancialMetrics(
                ticker=ticker,
                status="data_error",
                notes=[f"财报数据获取失败，需尽调: {e.message}"],
            )
        return self.analyze_report(
            report, trailing_pe=trailing_pe, expected_growth_pct=expected_growth_pct
        )

    def analyze_report(
        self,
        report: FinancialReport,
        trailing_pe: float | None = None,
        expected_growth_pct: float | None = None,
    ) -> FinancialMetrics:
        """对已获取的财报做纯计算（可离线测试）。"""
        notes: list[str] = []
        periods = report.periods
        m = FinancialMetrics(
            ticker=report.ticker,
            currency=report.currency,
            periods_used=len(periods),
            trailing_pe=trailing_pe,
        )

        if report.status == "data_error" or not periods:
            m.status = "data_error"
            m.notes = ["财报无有效报告期，需尽调"]
            return m

        first, last = periods[0], periods[-1]
        years = len(periods) - 1

        # 趋势与水平
        m.revenue_latest = last.revenue
        m.gross_margin_latest = last.gross_margin
        m.net_margin_latest = last.net_margin
        m.revenue_cagr = _cagr_pct(first.revenue, last.revenue, years)
        m.earnings_cagr = _cagr_pct(first.net_income, last.net_income, years)
        m.revenue_trend = _trend_value(first.revenue, last.revenue)
        m.gross_margin_trend = _trend_points(first.gross_margin, last.gross_margin)
        m.net_margin_trend = _trend_points(first.net_margin, last.net_margin)
        m.ocf_trend = _trend_value(first.operating_cashflow, last.operating_cashflow)
        if last.operating_cashflow is not None:
            m.ocf_latest_positive = last.operating_cashflow > 0

        if len(periods) >= 2 and periods[-2].revenue:
            prev = periods[-2].revenue
            if last.revenue is not None and prev:
                m.revenue_yoy = (last.revenue / prev - 1) * 100

        # forward PE
        if report.forward_pe is not None:
            m.forward_pe = report.forward_pe
            m.forward_pe_basis = "provider"
        elif trailing_pe is not None and expected_growth_pct is not None and (
            1 + expected_growth_pct / 100
        ) > 0:
            m.forward_pe = trailing_pe / (1 + expected_growth_pct / 100)
            m.forward_pe_basis = "derived_from_growth"
        elif (
            trailing_pe is not None
            and m.earnings_cagr is not None
            and (1 + m.earnings_cagr / 100) > 0
        ):
            m.forward_pe = trailing_pe / (1 + m.earnings_cagr / 100)
            m.forward_pe_basis = "derived_from_history"
        else:
            m.forward_pe = None
            m.forward_pe_basis = "unavailable"
            notes.append("前瞻估值数据不足（无前瞻盈利预期），需尽调")

        # PEG
        if report.peg_ratio is not None:
            m.peg_ratio = report.peg_ratio
        elif trailing_pe is not None and m.earnings_cagr is not None and m.earnings_cagr > 0:
            m.peg_ratio = trailing_pe / m.earnings_cagr

        # 数据完整性 → 状态
        missing = [
            name
            for name, val in (
                ("revenue", m.revenue_latest),
                ("net_margin", m.net_margin_latest),
                ("operating_cashflow", last.operating_cashflow),
            )
            if val is None
        ]
        if missing:
            notes.append(f"部分科目缺失（{', '.join(missing)}），相关结论需尽调")
            m.status = "partial"

        m.notes = notes
        return m

    # ---- 产出 Evidence（定量 link） ----

    def build_evidence(
        self, metrics: FinancialMetrics, condition: str | None = None
    ) -> Evidence:
        """把财务指标规则化为一份 Evidence（data 仅含真实计算值，不编造）。"""
        data = asdict(metrics)

        # 数据缺失 → 明确转尽调，不臆造支持度
        if metrics.status == "data_error":
            return Evidence(
                data=data,
                finding="财报数据缺失，无法形成定量证据，需人工尽调。",
                supports=False,
                confidence="低",
                needs_due_diligence=True,
            )

        finding = self._summarize(metrics)
        needs_dd = (
            metrics.forward_pe_basis == "unavailable" or metrics.status == "partial"
        )

        # 支持度启发式：增长不恶化 + 利润率不恶化 + 经营现金流为正
        positive_growth = metrics.revenue_trend in ("improving", "stable")
        positive_margin = metrics.net_margin_trend in ("improving", "stable")
        positive_cash = metrics.ocf_latest_positive is True
        supports = bool(positive_growth and positive_margin and positive_cash)

        # 置信度按数据完整度
        if metrics.periods_used >= 4 and not needs_dd:
            confidence = "高"
        elif metrics.periods_used >= 2:
            confidence = "中"
        else:
            confidence = "低"

        if needs_dd:
            finding += "（部分前瞻/科目数据不足，需尽调）"

        return Evidence(
            data=data,
            finding=finding,
            supports=supports,
            confidence=confidence,
            needs_due_diligence=needs_dd,
        )

    def evaluate(
        self,
        ticker: str,
        trailing_pe: float | None = None,
        expected_growth_pct: float | None = None,
        condition: str | None = None,
        max_periods: int = 5,
    ) -> Evidence:
        """便捷方法：抓取 → 分析 → 产出 Evidence。"""
        metrics = self.analyze_ticker(
            ticker,
            trailing_pe=trailing_pe,
            expected_growth_pct=expected_growth_pct,
            max_periods=max_periods,
        )
        return self.build_evidence(metrics, condition=condition)

    @staticmethod
    def _summarize(m: FinancialMetrics) -> str:
        """生成中文财务摘要（供 Evidence.finding）"""
        parts: list[str] = []
        if m.revenue_cagr is not None:
            parts.append(
                f"营收近{m.periods_used}期 CAGR {m.revenue_cagr:.1f}%（{m.revenue_trend}）"
            )
        elif m.revenue_trend != "unknown":
            parts.append(f"营收趋势 {m.revenue_trend}")
        if m.gross_margin_latest is not None:
            parts.append(
                f"毛利率 {m.gross_margin_latest:.1f}%（{m.gross_margin_trend}）"
            )
        if m.net_margin_latest is not None:
            parts.append(
                f"净利率 {m.net_margin_latest:.1f}%（{m.net_margin_trend}）"
            )
        if m.ocf_latest_positive is not None:
            parts.append(
                f"经营现金流{'为正' if m.ocf_latest_positive else '为负'}（{m.ocf_trend}）"
            )
        if m.forward_pe is not None:
            parts.append(
                f"forward PE {m.forward_pe:.1f}（{m.forward_pe_basis}）"
            )
        if m.peg_ratio is not None:
            parts.append(f"PEG {m.peg_ratio:.2f}")
        return "；".join(parts) + "。" if parts else "无可用财务指标。"
