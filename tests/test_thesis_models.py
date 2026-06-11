"""
S1–S5 多阶段流水线数据模型测试

覆盖 from_dict 解析（中/英/PRD 别名字段）、嵌套构造、validate() 通过/失败分支、
Field 约束触发的 ValidationError，以及 ThesisProjection 向后兼容的
to_projection_result()。对应 P1 Step 2。
"""
import pytest
from pydantic import ValidationError

from src.llm.models import (
    Evidence,
    LogicChain,
    LogicChainLink,
    ProxyAssignment,
    ProxyMapping,
    RefinedThesis,
    ThesisProjection,
    ThesisProjectionResult,
)


class TestRefinedThesis:
    """S1 RefinedThesis"""

    def test_from_dict_english_keys(self):
        rt = RefinedThesis.from_dict({
            "proposition": "核电具备类公用事业确定性与成长性",
            "success_conditions": ["AI 用电需求持续增长", "核电核准节奏维持"],
            "kill_criteria": ["核电核准长期停滞", "电价市场化大幅压缩利润"],
            "horizon": "3-5年",
        })
        assert rt.proposition.startswith("核电")
        assert len(rt.kill_criteria) == 2
        assert rt.validate() is True

    def test_from_dict_chinese_and_alias_keys(self):
        rt = RefinedThesis.from_dict({
            "命题": "命题文本",
            "成立条件": "单条成立条件",  # 字符串应被规整为单元素列表
            "falsification_criteria": ["证伪条件A"],
            "时间跨度": "2年",
        })
        assert rt.success_conditions == ["单条成立条件"]
        assert rt.kill_criteria == ["证伪条件A"]
        assert rt.horizon == "2年"
        assert rt.validate() is True

    def test_validate_requires_kill_criteria(self):
        """可证伪性是 S1 核心：缺 kill-criteria 应判定无效"""
        rt = RefinedThesis(
            proposition="命题",
            success_conditions=["成立条件"],
            kill_criteria=[],
            horizon="3年",
        )
        assert rt.validate() is False

    def test_validate_requires_success_conditions(self):
        rt = RefinedThesis(
            proposition="命题",
            success_conditions=[],
            kill_criteria=["证伪条件"],
            horizon="3年",
        )
        assert rt.validate() is False


class TestEvidence:
    """S4 Evidence"""

    def test_from_dict_with_string_supports_and_data(self):
        ev = Evidence.from_dict({
            "data": {"forward_pe": 7.5, "revenue_cagr": 0.18},
            "finding": "前瞻估值显著低于历史中枢",
            "supports": "是",
            "confidence": "高",
        })
        assert ev.supports is True
        assert ev.data["forward_pe"] == 7.5
        assert ev.confidence == "高"
        assert ev.validate() is True

    def test_from_dict_defaults_and_dd_flag(self):
        ev = Evidence.from_dict({
            "finding": "无公开 proxy，转人工尽调",
            "needs_due_diligence": True,
        })
        assert ev.confidence == "中"  # 默认
        assert ev.supports is False
        assert ev.needs_due_diligence is True
        assert ev.data == {}
        assert ev.validate() is True

    def test_invalid_confidence_raises_at_construction(self):
        with pytest.raises(ValidationError):
            Evidence(finding="x", confidence="medium")


class TestLogicChainLinkAndChain:
    """S2 LogicChain / LogicChainLink"""

    def test_chain_from_dict_builds_nested_links(self):
        chain = LogicChain.from_dict({
            "links": [
                {"statement": "上游燃料成本可控", "weight": 0.3, "condition": "铀价稳定"},
                {"陈述": "需求侧 AI 用电增长", "权重": 0.7, "条件": "算力扩张持续"},
            ]
        })
        assert len(chain.links) == 2
        assert chain.links[1].statement == "需求侧 AI 用电增长"
        assert chain.links[1].weight == 0.7
        assert chain.validate() is True

    def test_link_proxy_fields_default_none(self):
        link = LogicChainLink(statement="s", weight=0.5, condition="c")
        assert link.proxy_type is None
        assert link.proxy_spec is None
        assert link.evidence is None
        assert link.validate() is True

    def test_link_carries_evidence_when_present(self):
        link = LogicChainLink.from_dict({
            "statement": "s",
            "weight": 0.5,
            "condition": "c",
            "proxy_type": "quantitative",
            "proxy_spec": "yfinance forwardPE",
            "evidence": {"finding": "支持", "supports": True, "confidence": "中"},
        })
        assert link.proxy_type == "quantitative"
        assert isinstance(link.evidence, Evidence)
        assert link.evidence.supports is True

    def test_weight_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            LogicChainLink(statement="s", weight=1.5, condition="c")

    def test_empty_chain_is_invalid(self):
        assert LogicChain(links=[]).validate() is False

    def test_invalid_proxy_type_in_from_dict_is_dropped_to_none(self):
        link = LogicChainLink.from_dict(
            {"statement": "s", "weight": 0.5, "condition": "c", "proxy_type": "bogus"}
        )
        assert link.proxy_type is None


class TestProxyMapping:
    """S3 ProxyMapping"""

    def test_from_dict_builds_assignments(self):
        pm = ProxyMapping.from_dict({
            "assignments": [
                {"link_index": 0, "proxy_type": "quantitative", "proxy_spec": "income() 营收同比"},
                {"link_index": 1, "proxy_type": "due_diligence", "proxy_spec": "访谈前员工"},
            ]
        })
        assert len(pm.assignments) == 2
        assert pm.assignments[0].proxy_type == "quantitative"
        assert pm.assignments[1].proxy_type == "due_diligence"
        assert pm.validate() is True

    def test_empty_mapping_is_invalid(self):
        assert ProxyMapping(assignments=[]).validate() is False

    def test_invalid_proxy_type_raises(self):
        with pytest.raises(ValidationError):
            ProxyAssignment(link_index=0, proxy_type="bogus")


class TestThesisProjection:
    """S5 ThesisProjection（升级版 Module B）"""

    def test_from_dict_with_prd_alias_and_evidence_chain(self):
        tp = ThesisProjection.from_dict({
            "thesis_aligned": "是",
            "expected_growth_rate": 18.0,  # PRD 别名
            "confidence": "高",
            "reasoning": "综合财报趋势与前瞻估值，增长确定性较强且估值未充分反映。",
            "evidence_chain": [
                {"finding": "营收 CAGR 18%", "supports": True, "confidence": "高"},
                {"finding": "前瞻 PE 偏低", "supports": True, "confidence": "中"},
            ],
        })
        assert tp.thesis_aligned is True
        assert tp.our_growth == 18.0
        assert len(tp.evidence_chain) == 2
        assert all(isinstance(e, Evidence) for e in tp.evidence_chain)
        assert tp.validate() is True

    def test_validate_rejects_short_reasoning(self):
        tp = ThesisProjection(
            thesis_aligned=True, our_growth=10.0, confidence="中", reasoning="短"
        )
        assert tp.validate() is False

    def test_our_growth_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            ThesisProjection(
                thesis_aligned=True, our_growth=150.0, confidence="中",
                reasoning="这是一段足够长的推理说明，用于通过长度校验。",
            )

    def test_to_projection_result_preserves_spine_fields(self):
        tp = ThesisProjection(
            thesis_aligned=True,
            our_growth=20.0,
            confidence="高",
            reasoning="供应链重构与国产替代支撑长周期成长，估值修复空间大。",
            evidence_chain=[Evidence(finding="证据", supports=True, confidence="高")],
        )
        pr = tp.to_projection_result()
        assert isinstance(pr, ThesisProjectionResult)
        assert pr.our_growth == 20.0
        assert pr.confidence == "高"
        assert pr.thesis_aligned is True
        assert pr.validate() is True

    def test_old_serialization_without_weighted_support_still_parses(self):
        """缺口②向后兼容：旧产物（无 weighted_support 字段）仍可解析"""
        legacy_json = (
            '{"thesis_aligned": true, "our_growth": 7.0, "confidence": "低", '
            '"reasoning": "证据存在缺口，综合判断给出保守增长估计。", '
            '"evidence_chain": [{"finding": "营收增长", "supports": true, '
            '"confidence": "中", "needs_due_diligence": false, "data": {}}]}'
        )
        tp = ThesisProjection.model_validate_json(legacy_json)
        assert tp.weighted_support is None
        assert tp.validate() is True
        # from_dict 路径同样兼容
        tp2 = ThesisProjection.from_dict({
            "thesis_aligned": True, "our_growth": 7.0, "confidence": "低",
            "reasoning": "证据存在缺口，综合判断给出保守增长估计。",
        })
        assert tp2.weighted_support is None
        assert tp2.validate() is True

    def test_weighted_support_round_trip(self):
        tp = ThesisProjection(
            thesis_aligned=True, our_growth=10.0, confidence="中",
            reasoning="加权支持分与综合结论方向一致，给出中等置信。",
            weighted_support=0.59,
        )
        restored = ThesisProjection.model_validate_json(tp.model_dump_json())
        assert restored.weighted_support == 0.59
        assert ThesisProjection.from_dict(
            {"thesis_aligned": True, "our_growth": 10.0, "confidence": "中",
             "reasoning": "加权支持分与综合结论方向一致，给出中等置信。",
             "weighted_support": 0.59}
        ).weighted_support == 0.59

    def test_model_dump_json_round_trip(self):
        """可被 JSON 序列化/反序列化（ArtifactStore 持久化所需）"""
        tp = ThesisProjection(
            thesis_aligned=False,
            our_growth=-5.0,
            confidence="低",
            reasoning="证据不足，多数环节需转人工尽调，暂不支持原 thesis。",
            evidence_chain=[
                Evidence(finding="数据缺失", supports=False, confidence="低",
                         needs_due_diligence=True),
            ],
        )
        dumped = tp.model_dump_json()
        restored = ThesisProjection.model_validate_json(dumped)
        assert restored.our_growth == -5.0
        assert restored.evidence_chain[0].needs_due_diligence is True
        assert restored.validate() is True
