"""
ArtifactStore 测试

覆盖阶段产物 JSON 落盘 / 读回（含嵌套 pydantic 模型）、目录结构、可读中文、
list_stages，以及 OutputConfig.artifacts_dir 默认值。对应改进计划 P1 Step 6。
"""
from datetime import datetime

from src.config.models import OutputConfig
from src.llm.models import Evidence, RefinedThesis, ThesisProjection
from src.persistence import ArtifactStore


class TestArtifactStore:
    def test_save_and_path_layout(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        rt = RefinedThesis(
            proposition="命题X",
            success_conditions=["A"],
            kill_criteria=["B"],
            horizon="3-5年",
        )
        path = store.save_stage("601985.SH", datetime(2026, 6, 4), "refined_thesis", rt, index=1)
        assert path.exists()
        assert path.name == "S1_refined_thesis.json"
        # 目录布局：<base>/<ticker>/<date>/
        assert path.parent.name == "2026-06-04"
        assert path.parent.parent.name == "601985.SH"

    def test_round_trip_nested_model(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        proj = ThesisProjection(
            thesis_aligned=True,
            our_growth=18.0,
            confidence="高",
            reasoning="综合证据，命题在 3 年窗口内具备成长确定性。",
            evidence_chain=[
                Evidence(data={"forward_pe": 7.5}, finding="估值偏低", supports=True, confidence="高"),
            ],
        )
        store.save_stage("601985.SH", "2026-06-04", "thesis_projection", proj, index=5)
        loaded = store.load_stage(
            "601985.SH", "2026-06-04", "thesis_projection",
            model_cls=ThesisProjection, index=5,
        )
        assert isinstance(loaded, ThesisProjection)
        assert loaded.our_growth == 18.0
        assert loaded.evidence_chain[0].data["forward_pe"] == 7.5
        assert loaded.validate() is True

    def test_readable_chinese_not_escaped(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        rt = RefinedThesis(
            proposition="核电是物理刚需",
            success_conditions=["需求增长"],
            kill_criteria=["政策逆转"],
            horizon="5年",
        )
        path = store.save_stage("601985.SH", "2026-06-04", "refined_thesis", rt, index=1)
        text = path.read_text(encoding="utf-8")
        assert "核电是物理刚需" in text  # 未被转义为 \uXXXX

    def test_save_list_and_dict(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        evidence = [
            Evidence(finding="e1", supports=True, confidence="中"),
            Evidence(finding="e2", supports=False, confidence="低", needs_due_diligence=True),
        ]
        store.save_stage("X.SH", "2026-06-04", "evidence", evidence, index=4)
        loaded = store.load_stage("X.SH", "2026-06-04", "evidence", index=4)
        assert isinstance(loaded, list) and len(loaded) == 2
        assert loaded[1]["needs_due_diligence"] is True

        store.save_stage("X.SH", "2026-06-04", "dd_queue", {"links": [2]})
        dd = store.load_stage("X.SH", "2026-06-04", "dd_queue")
        assert dd["links"] == [2]

    def test_list_stages_sorted(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        rt = RefinedThesis(proposition="p", success_conditions=["a"], kill_criteria=["b"], horizon="3y")
        store.save_stage("X.SH", "2026-06-04", "refined_thesis", rt, index=1)
        store.save_stage("X.SH", "2026-06-04", "logic_chain", {"links": []}, index=2)
        stages = store.list_stages("X.SH", "2026-06-04")
        names = [p.name for p in stages]
        assert names == ["S1_refined_thesis.json", "S2_logic_chain.json"]

    def test_list_stages_empty_when_missing(self, tmp_path):
        store = ArtifactStore(base_dir=tmp_path)
        assert store.list_stages("NOPE.SH", "2026-06-04") == []


class TestOutputConfigArtifactsDir:
    def test_default_artifacts_dir(self):
        cfg = OutputConfig()
        assert cfg.artifacts_dir == "./output/artifacts"
