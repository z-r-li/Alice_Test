"""
离线测试用的假 LLM 客户端

FakeLLMClient 鸭子类型 (duck-type) 等价于 DeepSeekClient，为 Module A/B 及
S1–S5 各阶段返回固定的、可通过 validate() 的结构化结果，完全离线、确定性。
用于流水线 / 阶段测试，配合 mock 文本 / 财报提供者保持 CI 离线（P1）。

通过 fail_stage 可模拟某一阶段抛错，用于测试 ThesisPipeline 回退到单次投影。
"""
from __future__ import annotations

from src.llm.models import (
    ConsensusResult,
    Evidence,
    LogicChain,
    LogicChainLink,
    ProxyAssignment,
    ProxyMapping,
    RefinedThesis,
    ThesisProjection,
    ThesisProjectionResult,
)


class FakeLLMClient:
    """确定性假客户端（不发起任何网络调用）"""

    def __init__(
        self,
        *,
        n_links: int = 3,
        include_due_diligence: bool = True,
        our_growth: float = 18.0,
        implied_growth: float = 8.0,
        fail_stage: str | None = None,
        quant_irrelevant: bool = False,
    ):
        self.n_links = n_links
        self.include_due_diligence = include_due_diligence
        self.our_growth = our_growth
        self.implied_growth = implied_growth
        self.fail_stage = fail_stage
        self.quant_irrelevant = quant_irrelevant  # 模拟「指标与条件无关」的 LLM 判断
        self.calls: list[str] = []  # 记录调用顺序，供测试断言
        self.last_quant_kwargs: dict | None = None  # 最近一次定量判断入参
        self.last_synthesis_items: list[dict] | None = None  # 最近一次 S5 证据项
        self._thinking_enabled = False

    def _mark(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_stage == name:
            raise RuntimeError(f"FakeLLMClient: simulated failure at {name}")

    # ---- Module A / B（向后兼容路径）----

    def get_consensus(
        self, ticker, ticker_name, price_close, pe_ttm, pb, texts_content
    ) -> ConsensusResult:
        self._mark("get_consensus")
        return ConsensusResult(
            sentiment_score=35,
            sentiment_label="悲观",
            implied_growth=self.implied_growth,
            key_narrative="市场担忧短期增长放缓",
            key_worry="成本压力",
            key_hope="需求复苏",
        )

    def get_thesis_projection(
        self, ticker, ticker_name, user_thesis, industry="未知"
    ) -> ThesisProjectionResult:
        self._mark("get_thesis_projection")
        return ThesisProjectionResult(
            thesis_aligned=True,
            our_growth=self.our_growth,
            confidence="中",
            reasoning="单次投影回退路径：在信念框架下给出保守的增长估计。",
        )

    # ---- S1–S5 ----

    def get_refined_thesis(
        self, ticker, ticker_name, user_thesis, industry="未知"
    ) -> RefinedThesis:
        self._mark("get_refined_thesis")
        return RefinedThesis(
            proposition=f"{ticker_name} 在给定信念下具备长期成长性",
            success_conditions=["需求持续增长", "成本可控"],
            kill_criteria=["核心政策逆转", "毛利率持续下滑"],
            horizon="3-5年",
            original_thesis=user_thesis,
        )

    def get_logic_chain(
        self, ticker, ticker_name, proposition, success_conditions, kill_criteria, horizon
    ) -> LogicChain:
        self._mark("get_logic_chain")
        w = round(1.0 / self.n_links, 2)
        links = [
            LogicChainLink(
                statement=f"环节{i + 1}：影响命题的关键因素 {i + 1}",
                weight=w,
                condition=f"条件{i + 1} 需成立",
            )
            for i in range(self.n_links)
        ]
        return LogicChain(links=links, thesis_ref=proposition)

    def get_proxy_mapping(self, ticker, ticker_name, links) -> ProxyMapping:
        self._mark("get_proxy_mapping")
        assignments = []
        for i in range(len(links)):
            if i == 0:
                ptype, spec = "quantitative", "财报：营收/毛利/现金流趋势 + forward PE"
            elif i == 1:
                ptype, spec = "qualitative", "研报/新闻/互动易观点"
            elif self.include_due_diligence:
                ptype, spec = "due_diligence", "实地尽调：访谈前员工 / 现场核验"
            else:
                ptype, spec = "qualitative", "研报观点"
            assignments.append(
                ProxyAssignment(link_index=i, proxy_type=ptype, proxy_spec=spec)
            )
        return ProxyMapping(assignments=assignments)

    def get_evidence_interpretation(
        self, ticker, ticker_name, statement, condition, material
    ) -> Evidence:
        self._mark("get_evidence_interpretation")
        return Evidence(
            data={"source": "fake_material", "chars": len(material or "")},
            finding=f"基于素材判断「{statement}」的条件基本得到支持。",
            supports=True,
            confidence="中",
        )

    def get_quant_evidence_interpretation(
        self, ticker, ticker_name, statement, condition, metrics_summary
    ) -> Evidence:
        self._mark("get_quant_evidence_interpretation")
        self.last_quant_kwargs = {
            "ticker": ticker,
            "ticker_name": ticker_name,
            "statement": statement,
            "condition": condition,
            "metrics_summary": metrics_summary,
        }
        if self.quant_irrelevant:
            return Evidence(
                data={"llm_injected": True},  # 流水线必须丢弃，data 只认引擎值
                finding="指标为公司级财务，与该环节条件无关，无法检验。",
                supports=False,
                confidence="低",
                needs_due_diligence=True,
            )
        return Evidence(
            data={"llm_injected": True},  # 流水线必须丢弃，data 只认引擎值
            finding=f"引擎指标显示「{condition}」基本满足。",
            supports=True,
            confidence="中",
        )

    def get_thesis_synthesis(
        self, ticker, ticker_name, proposition, evidence_items
    ) -> ThesisProjection:
        self._mark("get_thesis_synthesis")
        self.last_synthesis_items = evidence_items
        return ThesisProjection(
            thesis_aligned=True,
            our_growth=self.our_growth,
            confidence="中",
            reasoning="综合各环节证据，命题在 3 年窗口内具备成长确定性，估值未充分反映。",
        )
