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

import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..config.models import ProxyLibraryConfig, TargetConfig
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
from .proxy_library import load_proxy_library, render_s3_library_block

# 加权支持分的置信系数（高/中/低）
_CONFIDENCE_FACTOR = {"高": 1.0, "中": 0.6, "低": 0.3}


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
    # #8：S2 驱动环节确定性校验的结果（供报告/main 摘要；不进 CSV 列）
    n_quantitative_drivers: int = 0  # 过完 S3 后仍为 quantitative 的环节数 (n_quant)
    s2_retried: bool = False  # 是否触发了一次有界 S2 驱动重试
    no_quantitative_anchor: bool = False  # 重试后仍 n_quant==0（our_growth 无定量锚）

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
        proxy_library_config: ProxyLibraryConfig | None = None,
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
            proxy_library_config: S3 proxy 备选库配置（config 顶层 proxy_library 块）。
                enabled=True 时在此加载库并渲染一次、随实例缓存进 S3 prompt；库不可用
                即抛 ProxyLibraryError（fail-closed，不得空库静默跑）。None 或
                enabled=False = 无库现行为（生产 kill switch）。
        """
        self._llm = llm_client
        self._provider_factory = financials_provider_factory
        self._fin_engine = financial_engine or FinancialAnalysisEngine()
        self._sanitizer = sanitizer or get_sanitizer()
        self._store = artifact_store
        self._logger = logger or logging.getLogger("alice_test")
        # S3 备选库段：启动即加载 + 渲染（确定性，按 id 排序），run() 逐次复用。
        # 加载失败直接抛（在 run() 的回退 try 之外），不会被静默吞成「已增强」假象。
        self._proxy_library_block: str | None = None
        if proxy_library_config is not None and proxy_library_config.enabled:
            entries = load_proxy_library(proxy_library_config.path)
            block = render_s3_library_block(entries)
            # 旧鸭子契约防呆（Codex #87 复审）：get_proxy_mapping 不接受 library_block
            # 的存量客户端若直接传参会 TypeError → run() 整体回退单次投影，静默丢掉
            # S1–S5。按签名探测：不支持则 WARNING + 不注入（回退无库 prompt），保住流水线。
            if self._client_accepts_library_block():
                self._proxy_library_block = block
            else:
                self._logger.warning(
                    "S3 客户端 get_proxy_mapping 不接受 library_block（旧鸭子类型契约），"
                    "proxy 备选库已加载但不注入 prompt；升级客户端签名以启用备选库。"
                )

    def _client_accepts_library_block(self) -> bool:
        """S3 客户端 get_proxy_mapping 是否接受 library_block kwarg（显式参数或 **kwargs）。

        无法内省（如 C 扩展）按不支持处理：错传 kwarg 的代价是整条流水线回退单次投影，
        比少注入一个备选库段严重得多。
        """
        fn = getattr(self._llm, "get_proxy_mapping", None)
        if fn is None:
            return False
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return False
        return "library_block" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )

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
        s2_snapshot = chain.model_copy(deep=True)  # S2 纯链路快照（proxy 前）

        # S3 Proxy 映射（合并回链路）+ 代码侧能力兜底
        mapping = self._map_and_enforce(chain, ticker, safe_name)

        # #8：确定性校验——过完 S3 后是否仍有可被引擎验证的驱动环节（唯一真源 = enforce 后
        # 仍为 quantitative 的环节数；is_proxy_computable 已在 enforce 内挡掉越界冒充）。
        n_quant = self._count_quantitative(chain)
        s2_retried = False
        no_quant_anchor = False
        no_anchor_reason: str | None = None
        if n_quant == 0:
            # 一次有界 S2 重试：明确要求至少 1 条白名单内的公司级财务驱动 condition。
            s2_retried = True
            self._logger.info(
                f"[{ticker}] S3 后无引擎可验证驱动环节 (n_quant=0)，触发一次 S2 驱动重试"
            )
            try:
                retry_chain = self._llm.get_logic_chain(
                    ticker=ticker, ticker_name=safe_name,
                    proposition=refined.proposition,
                    success_conditions=refined.success_conditions,
                    kill_criteria=refined.kill_criteria, horizon=refined.horizon,
                    enforce_driver=True,
                )
                retry_snapshot = retry_chain.model_copy(deep=True)
                retry_mapping = self._map_and_enforce(retry_chain, ticker, safe_name)
            except Exception as e:
                self._logger.warning(
                    f"[{ticker}] S2 驱动重试失败，保留原链路并标无定量锚: {e}"
                )
                retry_chain = None
            if retry_chain is not None:
                # 采用重试链路（更强约束下的最佳尝试）
                chain, mapping, s2_snapshot = retry_chain, retry_mapping, retry_snapshot
                n_quant = self._count_quantitative(chain)
            if n_quant == 0:
                # 重试仍无驱动：不编造定量，记可选标记，让 S5 与报告显式说明无锚。
                no_quant_anchor = True
                no_anchor_reason = (
                    "S2 经一次重试后仍无白名单内可被财务引擎验证的公司级财务驱动环节 "
                    "(n_quant=0)；our_growth 无定量锚，受限于 thesis 设计而非数据缺失。"
                )
                self._logger.warning(f"[{ticker}] {no_anchor_reason}")

        self._persist(ticker, audit_date, "logic_chain", s2_snapshot, 2)
        self._persist(ticker, audit_date, "proxy_mapping", mapping, 3)

        # S4 逐 link 证据
        metrics = self._financial_metrics(ticker, pe_ttm)
        dd_queue: list[dict] = []
        for i, link in enumerate(chain.links):
            link.evidence = self._evidence_for_link(
                link, metrics, material, ticker, safe_name
            )
            link.evidence = self._ensure_due_diligence(link.evidence)
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

        # S5 综合（带 S2 权重，按 weight 加权）
        evidence_items = [
            {
                "statement": l.statement,
                "weight": l.weight,
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
            no_quantitative_anchor=no_quant_anchor,
        )
        projection.evidence_chain = evidence_list
        projection.refined_thesis = refined
        projection.logic_chain = chain
        projection.weighted_support = self.weighted_support(chain)
        projection.no_quantitative_anchor = no_quant_anchor
        projection.no_anchor_reason = no_anchor_reason
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
            n_quantitative_drivers=n_quant,
            s2_retried=s2_retried,
            no_quantitative_anchor=no_quant_anchor,
        )

    def _map_and_enforce(
        self, chain: LogicChain, ticker: str, safe_name: str
    ) -> ProxyMapping:
        """S3：为链路逐环节匹配 proxy（合并回 chain）+ 代码侧能力兜底降级。

        抽成独立步骤，使 #8 的 S2 驱动重试能在新链路上重跑同一套映射 + enforce。
        """
        links_payload = [
            {"statement": l.statement, "weight": l.weight, "condition": l.condition}
            for l in chain.links
        ]
        # 备选库启用时才传 library_block kwarg：未启用路径与旧版调用逐字一致，
        # 也不强迫不认识该参数的鸭子类型客户端升级。
        extra_kwargs = (
            {"library_block": self._proxy_library_block}
            if self._proxy_library_block is not None
            else {}
        )
        mapping: ProxyMapping = self._llm.get_proxy_mapping(
            ticker=ticker, ticker_name=safe_name, links=links_payload, **extra_kwargs
        )
        for a in mapping.assignments:
            if 0 <= a.link_index < len(chain.links):
                chain.links[a.link_index].proxy_type = a.proxy_type
                chain.links[a.link_index].proxy_spec = a.proxy_spec
        self._enforce_proxy_capability(chain, ticker)
        return mapping

    @staticmethod
    def _count_quantitative(chain: LogicChain) -> int:
        """过完 S3 + enforce 后仍为 quantitative 的环节数 (n_quant)。

        enforce 已把越界（is_proxy_computable=False）的 quantitative 降级为 due_diligence，
        故此计数 == 引擎真正可验证的驱动环节数，与 S3 用同一真源（is_proxy_computable）。
        """
        return sum(1 for l in chain.links if l.proxy_type == "quantitative")

    def _enforce_proxy_capability(self, chain: LogicChain, ticker: str) -> None:
        """S3 代码侧兜底：把指向引擎算不出指标的 quantitative 环节降级为尽调。

        即便 S3 prompt 已给白名单，LLM 仍可能把行业/上游/订单/回购等越界 proxy 误标
        quantitative；此处按引擎能力边界校验，越界即转 due_diligence，绝不进定量证据路径
        （定量证据会用无关的公司财务冒充验证——验收报告 §五 P0-1 的根因）。
        """
        for i, link in enumerate(chain.links):
            if link.proxy_type != "quantitative":
                continue
            if self._fin_engine.is_proxy_computable(link.proxy_spec):
                continue
            orig = link.proxy_spec or "（未给 proxy_spec）"
            link.proxy_type = "due_diligence"
            link.proxy_spec = f"[引擎不可算→转尽调] {orig}"
            self._logger.info(
                f"[{ticker}] 环节{i} proxy 越界（非白名单指标），定量降级为尽调: {orig}"
            )

    @staticmethod
    def _ensure_due_diligence(ev: Evidence) -> Evidence:
        """确定性兜底：空 data + 低置信的证据自动转尽调入队，不依赖 LLM 自觉。

        典型场景：定性环节素材不足、LLM 给出「信息不足/无法判断」(confidence=低)，但
        定性 schema 无 needs_due_diligence 字段 → 否则与「无法判断」的 finding 自相矛盾地
        漏出尽调队列（验收报告 §五 P0-3）。

        只命中「真·空数据 + 低置信」：定量证据 data 恒为 asdict(metrics)（非空），故引擎的
        完整度缺口不会被这条规则再塞回队列，与 eb5cba5 的收窄一致。
        """
        if not ev.needs_due_diligence and not ev.data and ev.confidence == "低":
            return ev.model_copy(update={"needs_due_diligence": True})
        return ev

    def _evidence_for_link(
        self, link, metrics, material: str, ticker: str, safe_name: str
    ) -> Evidence:
        """按 proxy_type 产出该环节证据。"""
        ptype = link.proxy_type

        if ptype == "quantitative" and metrics is not None:
            # 定量：引擎计算指标 + 廉价 LLM 条件判断（data 仅含真实计算值）
            return self._quantitative_evidence(link, metrics, ticker, safe_name)

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

    @staticmethod
    def weighted_support(chain: LogicChain) -> float:
        """确定性加权支持分：Σ(weight × supports × 置信系数)，高/中/低 = 1.0/0.6/0.3。

        与 S5 的 LLM 综合相互独立，写进阶段产物供人工对照综合结论是否离谱。
        """
        total = 0.0
        for link in chain.links:
            ev = link.evidence
            if ev is None or not ev.supports:
                continue
            total += link.weight * _CONFIDENCE_FACTOR.get(ev.confidence, 0.3)
        return round(total, 4)

    def _quantitative_evidence(
        self, link, metrics, ticker: str, safe_name: str
    ) -> Evidence:
        """定量环节证据：引擎指标不变，由 LLM 判断指标是否支持该环节条件。

        - Evidence.data 永远只放引擎计算值（LLM 不得引入新数字）；
        - 指标与条件明显无关时 LLM 应判 needs_due_diligence=True，不强行给 supports；
        - LLM 调用失败回退到引擎启发式，并标 needs_due_diligence=True。

        是否尽调以 LLM 的按条件判断为准：引擎的公司级完整度缺口（partial /
        前瞻不可用）已含在指标摘要里，与条件无关时不应强制尽调；
        只有阻断性的 data_error 直接走引擎尽调路径。
        """
        base = self._fin_engine.build_evidence(metrics, condition=link.condition)
        if metrics.status == "data_error":
            return base  # 引擎已如实标尽调，无需再让 LLM 判断
        try:
            judged = self._llm.get_quant_evidence_interpretation(
                ticker=ticker, ticker_name=safe_name,
                statement=link.statement, condition=link.condition,
                metrics_summary=self._fin_engine.metrics_summary(metrics),
            )
        except Exception as e:
            self._logger.warning(
                f"[{ticker}] 定量证据条件判断失败，回退启发式并转尽调: {e}"
            )
            return base.model_copy(update={"needs_due_diligence": True})
        return Evidence(
            data=base.data,
            finding=judged.finding,
            supports=judged.supports,
            confidence=judged.confidence,
            needs_due_diligence=judged.needs_due_diligence,
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
