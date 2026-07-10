"""coverage 四计数单元测试（100Step 借鉴 PR②）。

`AliceTestPipeline._coverage_counts`：由 PipelineResult.logic_chain.links（S3 enforce
之后口径）计 (total, quant, evidenced, dd)。核心纪律：
- 无 chain（fail-closed / 流水线回退 / pipeline 关闭）→ 全 None，**不造 0**；
- 0 是「拆了链但该计数为空」的真实观测，与 None（没走到那）语义不同；
- dd 按环节去重：proxy_type=due_diligence 且 evidence.needs_due_diligence 只计 1。
"""
from src.engines.thesis_pipeline import PipelineResult
from src.llm.models import Evidence, LogicChain, LogicChainLink, ThesisProjection
from src.main import AliceTestPipeline


def _link(ptype=None, evidence=None):
    return LogicChainLink(
        statement="环节陈述", weight=0.25, condition="条件成立",
        proxy_type=ptype, evidence=evidence,
    )


def _ev(needs_dd=False):
    return Evidence(
        data={"k": 1}, finding="发现", supports=True,
        confidence="中", needs_due_diligence=needs_dd,
    )


def _pr(links=None, used=True):
    projection = ThesisProjection(
        thesis_aligned=True, our_growth=10.0, confidence="中", reasoning="r"
    )
    chain = None if links is None else LogicChain(links=links)
    return PipelineResult(projection=projection, logic_chain=chain, used_pipeline=used)


class TestCoverageCounts:
    def test_mixed_chain_counts(self):
        # quantitative(有证据) + qualitative(证据转尽调) + due_diligence(证据也标尽调)
        # + 未分配 proxy(无证据) → total=4, quant=1, evidenced=3, dd=2（尽调按环节去重）
        links = [
            _link("quantitative", _ev()),
            _link("qualitative", _ev(needs_dd=True)),
            _link("due_diligence", _ev(needs_dd=True)),
            _link(None, None),
        ]
        assert AliceTestPipeline._coverage_counts(_pr(links)) == (4, 1, 3, 2)

    def test_dd_dedups_per_link(self):
        # 同一环节既是 due_diligence 又带 needs_due_diligence 证据 → 只计 1 环节
        links = [_link("due_diligence", _ev(needs_dd=True))]
        total, quant, evidenced, dd = AliceTestPipeline._coverage_counts(_pr(links))
        assert (total, quant, evidenced, dd) == (1, 0, 1, 1)

    def test_dd_counts_evidence_flag_without_dd_proxy(self):
        # quantitative 环节的证据判「需尽调」→ 计入 dd（handoff：或 needs_due_diligence）
        links = [_link("quantitative", _ev(needs_dd=True))]
        assert AliceTestPipeline._coverage_counts(_pr(links)) == (1, 1, 1, 1)

    def test_none_pipeline_result_all_none(self):
        assert AliceTestPipeline._coverage_counts(None) == (None, None, None, None)

    def test_fallback_no_chain_all_none(self):
        # 流水线整体回退（used_pipeline=False、无 chain）→ 全 None（没走到那），不造 0
        assert AliceTestPipeline._coverage_counts(
            _pr(links=None, used=False)
        ) == (None, None, None, None)

    def test_fallback_with_chain_still_none(self):
        # 防御：即便回退结果意外带 chain，也不产计数——回退行绕过了证据链守门
        assert AliceTestPipeline._coverage_counts(
            _pr(links=[_link("quantitative", _ev())], used=False)
        ) == (None, None, None, None)

    def test_empty_chain_counts_zero_not_none(self):
        # 拆了链但空：0 是真实观测（与 None 语义不同）
        assert AliceTestPipeline._coverage_counts(_pr(links=[])) == (0, 0, 0, 0)
