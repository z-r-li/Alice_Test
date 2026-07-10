"""
S3 proxy 备选库测试（100Step 借鉴 PR①）

离线覆盖（对应交接文档「测试」节）：
1. yaml schema：字段齐全、id 唯一、type_hint/engine_computable 取值合法；
2. 库⇔词表一致性（不变量 2）：engine_computable=true 条目的 spec_template 必须
   is_proxy_computable == True，false 条目必须 == False；
3. 渲染：包含全部 id、按 id 排序、两次渲染字节一致（prompt 确定性，不变量 3）；
4. fail-closed（不变量 4）：yaml 缺失 / malformed / 字段非法 / 空库 → ProxyLibraryError；
5. ThesisPipeline 接线：enabled 时 S3 收到备选库段、disabled/None 时现行为不变、
   库不可用时启动抛错（不会被 run() 的回退吞掉）。
"""
import pytest

from src.config.models import ProxyLibraryConfig
from src.engines.financial_analysis import FinancialAnalysisEngine
from src.engines.proxy_library import (
    ProxyEntry,
    ProxyLibraryError,
    load_proxy_library,
    render_s3_library_block,
)
from src.engines.thesis_pipeline import ThesisPipeline
from tests.fakes import FakeLLMClient


@pytest.fixture(scope="module")
def entries() -> list[ProxyEntry]:
    return load_proxy_library()


# ---------------------------------------------------------------- schema ----


class TestLibrarySchema:
    def test_loads_nonempty_with_all_fields(self, entries):
        assert len(entries) >= 30  # v0.1 起步稿规模；防止条目被误删成小库
        for e in entries:
            assert e.id and e.name and e.category
            assert e.spec_template and e.source_hint and e.cadence
            assert e.applicability
            assert isinstance(e.note, str)  # note 允许为空串

    def test_ids_unique(self, entries):
        ids = [e.id for e in entries]
        assert len(ids) == len(set(ids))

    def test_type_hint_and_computable_legal(self, entries):
        for e in entries:
            assert e.type_hint in {"quantitative", "qualitative", "due_diligence"}
            assert isinstance(e.engine_computable, bool)
            if e.engine_computable:
                # 硬规则：仅 quantitative 条目可标引擎可算
                assert e.type_hint == "quantitative", e.id

    def test_expected_groups_present(self, entries):
        groups = {e.id[0] for e in entries}
        assert groups == {"Q", "G", "D", "S", "C", "E", "H", "X"}


# ------------------------------------------------- 库⇔词表一致性（不变量 2）----


class TestWordlistConsistency:
    def test_engine_computable_matches_is_proxy_computable(self, entries):
        """全库逐条：engine_computable 必须与 is_proxy_computable(spec_template) 一致。

        已知坑：spec 裸出现「盈利/毛利率」等白名单词而无黑名单词会被误判可算——
        改条目措辞前必须先过本测试。
        """
        for e in entries:
            actual = FinancialAnalysisEngine.is_proxy_computable(e.spec_template)
            assert actual == e.engine_computable, (
                f"{e.id} engine_computable={e.engine_computable} 但 "
                f"is_proxy_computable={actual}: {e.spec_template!r}"
            )

    def test_computable_entries_are_exactly_q01_to_q08(self, entries):
        """S3 prompt 备选库段写死「本库仅 Q01–Q08 属此档」——加减可算条目须同步改 prompt 文案。"""
        computable_ids = {e.id for e in entries if e.engine_computable}
        assert computable_ids == {f"Q0{i}" for i in range(1, 9)}


# ------------------------------------------------------- 渲染（不变量 3）----


class TestRendering:
    def test_block_contains_all_ids_sorted(self, entries):
        block = render_s3_library_block(entries)
        positions = [block.index(f"- [{eid}] ") for eid in sorted(e.id for e in entries)]
        assert positions == sorted(positions)  # 按 id 升序出现
        assert len(block.splitlines()) == len(entries)  # 逐条单行

    def test_line_format(self, entries):
        block = render_s3_library_block(entries)
        q01 = next(l for l in block.splitlines() if l.startswith("- [Q01]"))
        assert q01.startswith("- [Q01] 营收增速趋势（quantitative·引擎可算）：")
        assert "｜来源:" in q01 and "｜频率:" in q01
        g01 = next(l for l in block.splitlines() if l.startswith("- [G01]"))
        assert "（qualitative）" in g01 and "引擎可算" not in g01

    def test_render_deterministic_across_loads(self):
        """同一 yaml 两次加载 + 渲染字节一致（无时间戳 / 随机成分）。"""
        block1 = render_s3_library_block(load_proxy_library())
        block2 = render_s3_library_block(load_proxy_library())
        assert block1 == block2

    def test_render_sorts_unsorted_input(self, entries):
        block_sorted = render_s3_library_block(entries)
        block_reversed = render_s3_library_block(list(reversed(entries)))
        assert block_sorted == block_reversed


# ---------------------------------------------------- fail-closed（不变量 4）----


def _write_lib(tmp_path, body: str):
    p = tmp_path / "lib.yaml"
    p.write_text(body, encoding="utf-8")
    return str(p)


_VALID_ENTRY = """\
version: "0.1"
entries:
  - id: Q01
    name: 营收增速趋势
    category: 估值财务
    type_hint: quantitative
    engine_computable: true
    spec_template: "财务引擎：营收同比与近3-5期营收CAGR"
    source_hint: 东财
    cadence: 季
    applicability: ALL
    note: ""
"""


class TestFailClosed:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ProxyLibraryError, match="不存在"):
            load_proxy_library(str(tmp_path / "nope.yaml"))

    def test_malformed_yaml_raises(self, tmp_path):
        path = _write_lib(tmp_path, "entries: [unclosed")
        with pytest.raises(ProxyLibraryError, match="解析失败"):
            load_proxy_library(path)

    def test_non_mapping_top_level_raises(self, tmp_path):
        path = _write_lib(tmp_path, "- 只是个列表")
        with pytest.raises(ProxyLibraryError, match="结构非法"):
            load_proxy_library(path)

    def test_empty_entries_raises(self, tmp_path):
        path = _write_lib(tmp_path, "version: '0.1'\nentries: []")
        with pytest.raises(ProxyLibraryError, match="空"):
            load_proxy_library(path)

    def test_missing_field_raises(self, tmp_path):
        body = _VALID_ENTRY.replace("    cadence: 季\n", "")
        with pytest.raises(ProxyLibraryError, match="缺字段"):
            load_proxy_library(_write_lib(tmp_path, body))

    def test_unknown_field_raises(self, tmp_path):
        body = _VALID_ENTRY + "    extra_field: 漂移\n"
        with pytest.raises(ProxyLibraryError, match="未知字段"):
            load_proxy_library(_write_lib(tmp_path, body))

    def test_duplicate_id_raises(self, tmp_path):
        body = _VALID_ENTRY + _VALID_ENTRY[_VALID_ENTRY.index("  - id: Q01"):]
        with pytest.raises(ProxyLibraryError, match="重复"):
            load_proxy_library(_write_lib(tmp_path, body))

    def test_invalid_type_hint_raises(self, tmp_path):
        body = _VALID_ENTRY.replace("type_hint: quantitative", "type_hint: magic")
        with pytest.raises(ProxyLibraryError, match="type_hint 非法"):
            load_proxy_library(_write_lib(tmp_path, body))

    def test_non_bool_computable_raises(self, tmp_path):
        body = _VALID_ENTRY.replace("engine_computable: true", "engine_computable: 是")
        with pytest.raises(ProxyLibraryError, match="布尔"):
            load_proxy_library(_write_lib(tmp_path, body))

    def test_computable_requires_quantitative(self, tmp_path):
        body = _VALID_ENTRY.replace("type_hint: quantitative", "type_hint: qualitative")
        with pytest.raises(ProxyLibraryError, match="quantitative"):
            load_proxy_library(_write_lib(tmp_path, body))

    def test_explicit_path_loads_same_as_packaged(self):
        packaged = load_proxy_library()
        explicit = load_proxy_library("src/engines/resources/proxy_library.yaml")
        assert packaged == explicit


# ------------------------------------------------- ThesisPipeline 接线 ----


class TestPipelineWiring:
    def test_enabled_passes_rendered_block_to_s3(self):
        fake = FakeLLMClient(n_links=3)
        pipeline = ThesisPipeline(
            fake, proxy_library_config=ProxyLibraryConfig(enabled=True)
        )
        assert pipeline._proxy_library_block is not None  # 启动即加载缓存
        from src.config.models import TargetConfig

        pipeline.run(TargetConfig(ticker="601985.SH", name="中国核电", thesis="信念"))
        assert fake.last_library_block is not None
        assert "- [Q01]" in fake.last_library_block
        assert "- [X02]" in fake.last_library_block

    def test_disabled_keeps_current_behavior(self):
        fake = FakeLLMClient(n_links=3)
        pipeline = ThesisPipeline(
            fake, proxy_library_config=ProxyLibraryConfig(enabled=False)
        )
        assert pipeline._proxy_library_block is None
        from src.config.models import TargetConfig

        pipeline.run(TargetConfig(ticker="601985.SH", name="中国核电", thesis="信念"))
        assert fake.last_library_block is None

    def test_omitted_config_keeps_current_behavior(self):
        pipeline = ThesisPipeline(FakeLLMClient(n_links=3))
        assert pipeline._proxy_library_block is None

    def test_enabled_with_bad_path_raises_at_startup(self, tmp_path):
        """fail-closed：enabled=true 而 yaml 不可用 → 构造即抛错，不落入 run() 的回退。"""
        with pytest.raises(ProxyLibraryError):
            ThesisPipeline(
                FakeLLMClient(),
                proxy_library_config=ProxyLibraryConfig(
                    enabled=True, path=str(tmp_path / "missing.yaml")
                ),
            )

    def test_disabled_ignores_bad_path(self, tmp_path):
        """kill switch 优先：enabled=false 时不读 path，不因坏路径拒绝启动。"""
        pipeline = ThesisPipeline(
            FakeLLMClient(),
            proxy_library_config=ProxyLibraryConfig(
                enabled=False, path=str(tmp_path / "missing.yaml")
            ),
        )
        assert pipeline._proxy_library_block is None


# ------------------------------------------------------------- config ----


class TestProxyLibraryConfig:
    def test_defaults_enabled_with_packaged_file(self):
        cfg = ProxyLibraryConfig()
        assert cfg.enabled is True
        assert cfg.path is None

    def test_appconfig_has_default_block(self):
        from src.config.models import AppConfig

        cfg = AppConfig(targets=[])
        assert cfg.proxy_library.enabled is True
        assert cfg.proxy_library.path is None

    def test_rejects_unknown_keys(self):
        with pytest.raises(Exception):
            ProxyLibraryConfig(enabled=True, unknown_key=1)
