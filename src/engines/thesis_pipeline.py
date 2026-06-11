"""
S1–S5 多阶段信念流水线 (ThesisPipeline)

由 Module B 的「单次 LLM 投影」演进为可审查的多阶段流水线：

    S1 RefinedThesis → S2 LogicChain → S3 ProxyMapping（合并回链路）
    → S4 逐 link Evidence（定量走 FinancialAnalysisEngine、定性走 LLM、
       无 proxy → due-diligence 队列）→ S5 ThesisProjection（综合，带证据链）

每阶段产物经 ArtifactStore 单独持久化、可审查。最终产出 ThesisProjection，
经 .to_projection_result() 退化为向后兼容的 ThesisProjectionResult 喂给 GapCalculator
（脊柱 gap = our_growth − implied_growth 不变）。

护栏：任一阶段失败（内容审核 / JSON / 网络）整体回退到单次 get_thesis_projection，
保证总能产出 AuditResult；缺数据的环节如实进 due-diligence 队列，绝不编造。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..config.models import TargetConfig
from ..llm.models import (
    Evidence,
    LogicChain,
    ProxyMapping,
    RefinedThesis,
    ThesisProjection,
    ThesisProjectionResult,
)
from ..utils.sanitizer import TextSanitizer, get_sanitizer
from .financial_analysis import FinancialAnalysisEngine


@dataclass
class PipelineResult:
    """流水线输出（含可审查的证据链与尽调队列）"""

    projection: ThesisProjection
    refined_thesis: RefinedThesis | None = None
    logic_chain: LogicChain | None = None
    evidence: list[Evidence] = field(default_factory=list)
    due_diligence_queue: list[dict] = field(default_factory=list)
    used_pipeline: bool = True  # False 表示回退到了单次投影
    artifact_dir: str | None = None

    def to_projection_result(self) -> ThesisProjectionResult:
        """退化为向后兼容的 ThesisProjectionResult（喂给 GapCalculator）"""
        return self.projection.to_projection_result()


class ThesisPipeline:
    """S1–S5 信念流水线（升级版 Module B）"""

    def __init__(
        self,
        llm_client: Any,
        *,
        financials_provider_factory: Callable[[str], Any] | None = None,
        financial_engine: FinancialAnalysisEngine | None = None,
        sanitizer: TextSanitizer | None = None,
        artifact_store: Any | None = None,
        logger: logging.Logger | None = None,
    ):
        """
        Args:
            llm_client: DeepSeekClient（或鸭子类型等价物，如测试的 FakeLLMClient）
            financials_provider_factory: ticker -> FinancialsProvider 的工厂（S4 定量证据用）；
                为 None 时定量环节转尽调
            financial_engine: 纯计算的 FinancialAnalysisEngine（默认新建一个无 provider 的）
            sanitizer: 文本脱敏器（默认全局单例）
            artifact_store: ArtifactStore（为 None 时不持久化）
            logger: 日志器
        """
        self._llm = llm_client
        self._provider_factory = financials_provider_factory
        self._fin_engine = financial_engine or FinancialAnalysisEngine()
        self._sanitizer = sanitizer or get_sanitizer()
        self._store = artifact_store
        self._logger = logger or logging.getLogger("alice_test")

    def run(
        self,
        target: TargetConfig,
        *,
        quote: Any | None = None,
        texts: list | None = None,
        audit_date: datetime | None = None,
    ) -> PipelineResult:
        """执行 S1–S5；任一阶段失败回退到单次投影。"""
        try:
            return self._run_stages(target, quote=quote, texts=texts, audit_date=audit_date)
        except Exception as e:
            self._logger.warning(
                f"[{target.ticker}] ThesisPipeline 失败，回退单次投影: {e}"
            )
            return self._fallback(target)

    # ------------------------------------------------------------------ #

    def _run_stages(
        self,
        target: TargetConfig,
        *,
        quote: Any | None,
        texts: list | None,
        audit_date: datetime | None,
    ) -> PipelineResult:
        ticker = target.ticker
        safe_name = self._sanitizer.sanitize(target.name)
        safe_thesis = self._sanitizer.sanitize(target.thesis)
        industry = getattr(target, "industry", "未知") or "未知"
        safe_industry = self._sanitizer.sanitize(industry)
        pe_ttm = getattr(quote, "pe_ttm", None) if quote is not None else None
        material = self._build_material(texts)

        # S1 完善
        refined = self._llm.get_refined_thesis(
            ticker=ticker, ticker_name=safe_name, user_thesis=safe_thesis,
            industry=safe_industry,
        )
        self._persist(ticker, audit_date, "refined_thesis", refined, 1)

        # S2 逻辑链路
        chain = self._llm.get_logic_chain(
            ticker=ticker, ticker_name=safe_name, proposition=refined.proposition,
            success_conditions=refined.success_conditions,
            kill_criteria=refined.kill_criteria, horizon=refined.horizon,
        )
        self._persist(ticker, audit_date, "logic_chain", chain, 2)

        # S3 Proxy 映射（合并回链路）
        links_payload = [
            {"statement": l.statement, "weight": l.weight, "condition": l.condition}
            for l in chain.links
        ]
        mapping: ProxyMapping = self._llm.get_proxy_mapping(
            ticker=ticker, ticker_name=safe_name, links=links_payload
        )
        for a in mapping.assignments:
            if 0 <= a.link_index < len(chain.links):
                chain.links[a.link_index].proxy_type = a.proxy_type
                chain.links[a.link_index].proxy_spec = a.proxy_spec
        self._persist(ticker, audit_date, "proxy_mapping", mapping, 3)

        # S4 逐 link 证据
        metrics = self._financial_metrics(ticker, pe_ttm)
        dd_queue: list[dict] = []
        for i, link in enumerate(chain.links):
            link.evidence = self._evidence_for_link(
                link, metrics, material, ticker, safe_name
            )
            if link.evidence.needs_due_diligence:
                dd_queue.append(
                    {
                        "index": i,
                        "statement": link.statement,
                        "proxy_type": link.proxy_type,
                        "proxy_spec": link.proxy_spec,
                    }
                )
        evidence_list = [l.evidence for l in chain.links if l.evidence is not None]
        self._persist(
            ticker, audit_date, "evidence",
            {"evidence": evidence_list, "due_diligence_queue": dd_queue}, 4,
        )

        # S5 综合
        evidence_items = [
            {
                "statement": l.statement,
                "proxy_type": l.proxy_type,
                "supports": (l.evidence.supports if l.evidence else None),
                "confidence": (l.evidence.confidence if l.evidence else None),
                "finding": (l.evidence.finding if l.evidence else ""),
            }
            for l in chain.links
        ]
        projection: ThesisProjection = self._llm.get_thesis_synthesis(
            ticker=ticker, ticker_name=safe_name,
            proposition=refined.proposition, evidence_items=evidence_items,
        )
        projection.evidence_chain = evidence_list
        projection.refined_thesis = refined
        projection.logic_chain = chain
        self._persist(ticker, audit_date, "thesis_projection", projection, 5)

        artifact_dir = (
            str(self._store.run_dir(ticker, audit_date)) if self._store else None
        )
        return PipelineResult(
            projection=projection,
            refined_thesis=refined,
            logic_chain=chain,
            evidence=evidence_list,
            due_diligence_queue=dd_queue,
            used_pipeline=True,
            artifact_dir=artifact_dir,
        )

    def _evidence_for_link(
        self, link, metrics, material: str, ticker: str, safe_name: str
    ) -> Evidence:
        """按 proxy_type 产出该环节证据。"""
        ptype = link.proxy_type

        if ptype == "quantitative" and metrics is not None:
            # 定量：财报引擎规则化证据（data 仅含真实计算值）
            return self._fin_engine.build_evidence(metrics, condition=link.condition)

        if ptype == "qualitative":
            try:
                return self._llm.get_evidence_interpretation(
                    ticker=ticker, ticker_name=safe_name,
                    statement=link.statement, condition=link.condition,
                    material=material,
                )
            except Exception as e:
                self._logger.warning(f"[{ticker}] 定性证据获取失败，转尽调: {e}")
                return Evidence(
                    finding=f"定性证据获取失败，需人工尽调: {e}",
                    supports=False, confidence="低", needs_due_diligence=True,
                )

        # due_diligence / none / 未分配 / 定量但缺财报数据 → 转尽调，不编造
        spec = link.proxy_spec or "无可用 proxy"
        return Evidence(
            data={},
            finding=f"该环节无可量化/定性 proxy（{ptype or 'none'}）：{spec}，需人工尽调。",
            supports=False, confidence="低", needs_due_diligence=True,
        )

    def _financial_metrics(self, ticker: str, pe_ttm: float | None):
        """抓取并分析财报；失败返回 None（定量环节转尽调，不编造）。"""
        if self._provider_factory is None:
            return None
        try:
            provider = self._provider_factory(ticker)
            report = provider.get_financials(ticker, max_periods=5)
            return self._fin_engine.analyze_report(report, trailing_pe=pe_ttm)
        except Exception as e:
            self._logger.warning(f"[{ticker}] 财报分析失败，相关定量环节转尽调: {e}")
            return None

    def _build_material(self, texts: list | None, max_chars: int = 4000) -> str:
        """把抓取文本拼成（脱敏后的）分析素材，供定性证据判断。"""
        if not texts:
            return ""
        lines = []
        for t in texts:
            title = self._sanitizer.sanitize(getattr(t, "title", "") or "")
            summary = self._sanitizer.sanitize(getattr(t, "summary", "") or "")
            src = getattr(t, "source", "")
            typ = getattr(t, "type", "")
            lines.append(f"[{src}/{typ}] {title}: {summary}")
        return "\n".join(lines)[:max_chars]

    def _persist(self, ticker, audit_date, stage, artifact, index) -> None:
        if self._store is None:
            return
        try:
            self._store.save_stage(ticker, audit_date, stage, artifact, index=index)
        except Exception as e:  # 持久化失败不应中断分析
            self._logger.warning(f"[{ticker}] 阶段产物持久化失败 ({stage}): {e}")

    def _fallback(self, target: TargetConfig) -> PipelineResult:
        """整体失败时回退到单次投影（向后兼容路径）。"""
        safe_name = self._sanitizer.sanitize(target.name)
        safe_thesis = self._sanitizer.sanitize(target.thesis)
        industry = getattr(target, "industry", "未知") or "未知"
        safe_industry = self._sanitizer.sanitize(industry)
        pr = self._llm.get_thesis_projection(
            ticker=target.ticker, ticker_name=safe_name,
            user_thesis=safe_thesis, industry=safe_industry,
        )
        projection = ThesisProjection(
            thesis_aligned=pr.thesis_aligned,
            our_growth=pr.our_growth,
            confidence=pr.confidence,
            reasoning=pr.reasoning,
        )
        return PipelineResult(projection=projection, used_pipeline=False)
