"""
S3 proxy 备选库（100Step 借鉴 PR①）

从包内 `resources/proxy_library.yaml`（或 config 显式 path）加载 proxy 备选条目，
渲染为 S3 系统指令的「proxy 备选库」段，把 proxy 提案从「LLM 从零发明」变为
「从备选库选型 + 允许补充」。

护栏（对应交接文档不变量）：
- fail-closed：yaml 缺失 / malformed / 字段非法 / 空库 → 抛 ProxyLibraryError，
  不得静默降级空库跑（那会假装「已增强」）。
- 库⇔词表一致性由测试锁定（tests/test_proxy_library.py）：engine_computable=true
  条目的 spec_template 必须 `FinancialAnalysisEngine.is_proxy_computable(...) == True`，
  false 条目必须 == False；本模块不 import 引擎，避免循环耦合。
- prompt 确定性：渲染按 id 排序、无时间戳 / 随机成分，同一 yaml 两次渲染字节一致。
- 库只影响 S3 提案质量：`_enforce_proxy_capability` 仍是唯一定量裁判，越界
  quantitative 照旧被降级 due_diligence。
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

# 包内默认资源（config.proxy_library.path=null 时读取）
_RESOURCE_PACKAGE = "src.engines"
_RESOURCE_NAME = "resources/proxy_library.yaml"

_VALID_TYPE_HINTS = frozenset({"quantitative", "qualitative", "due_diligence"})
_REQUIRED_FIELDS = (
    "id", "name", "category", "type_hint", "engine_computable",
    "spec_template", "source_hint", "cadence", "applicability", "note",
)
# note 允许为空串（部分条目无补充说明），其余字符串字段必须非空
_NONEMPTY_STR_FIELDS = (
    "id", "name", "category", "spec_template", "source_hint", "cadence",
    "applicability",
)


class ProxyLibraryError(ValueError):
    """proxy 备选库不可用（缺失 / malformed / 字段非法）——fail-closed，启动即抛。"""


@dataclass(frozen=True)
class ProxyEntry:
    """备选库单条目（字段与 proxy_library.yaml 一一对应）"""

    id: str
    name: str
    category: str
    type_hint: str
    engine_computable: bool
    spec_template: str
    source_hint: str
    cadence: str
    applicability: str
    note: str


def _read_library_text(path: str | None) -> str:
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise ProxyLibraryError(f"proxy 备选库文件不存在: {path}")
        try:
            return p.read_text(encoding="utf-8")
        except OSError as e:
            raise ProxyLibraryError(f"proxy 备选库文件不可读: {path}: {e}") from e
    try:
        res = resources.files(_RESOURCE_PACKAGE).joinpath(_RESOURCE_NAME)
        return res.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        raise ProxyLibraryError(
            f"包内 proxy 备选库资源不可读 ({_RESOURCE_PACKAGE}/{_RESOURCE_NAME}): {e}"
        ) from e


def _parse_entry(raw: object, index: int, seen_ids: set[str]) -> ProxyEntry:
    where = f"entries[{index}]"
    if not isinstance(raw, dict):
        raise ProxyLibraryError(f"{where} 非映射: {raw!r}")

    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ProxyLibraryError(f"{where} 缺字段: {missing}")
    unknown = [k for k in raw if k not in _REQUIRED_FIELDS]
    if unknown:
        raise ProxyLibraryError(f"{where} 含未知字段: {unknown}")

    for f in _REQUIRED_FIELDS:
        if f == "engine_computable":
            continue
        v = raw[f]
        # yaml 会把无引号的 "1.0"/"true" 解析成非 str，一并挡住
        if not isinstance(v, str):
            raise ProxyLibraryError(f"{where}.{f} 须为字符串，实际 {type(v).__name__}")
        if f in _NONEMPTY_STR_FIELDS and not v.strip():
            raise ProxyLibraryError(f"{where}.{f} 不得为空")

    entry_id = raw["id"].strip()
    if entry_id in seen_ids:
        raise ProxyLibraryError(f"{where} id 重复: {entry_id}")
    seen_ids.add(entry_id)

    type_hint = raw["type_hint"]
    if type_hint not in _VALID_TYPE_HINTS:
        raise ProxyLibraryError(
            f"{where}.type_hint 非法: {type_hint!r}（须为 {sorted(_VALID_TYPE_HINTS)}）"
        )

    computable = raw["engine_computable"]
    if not isinstance(computable, bool):
        raise ProxyLibraryError(
            f"{where}.engine_computable 须为布尔，实际 {type(computable).__name__}"
        )
    if computable and type_hint != "quantitative":
        raise ProxyLibraryError(
            f"{where} engine_computable=true 仅允许 type_hint=quantitative，"
            f"实际 {type_hint}"
        )

    return ProxyEntry(
        id=entry_id,
        name=raw["name"],
        category=raw["category"],
        type_hint=type_hint,
        engine_computable=computable,
        spec_template=raw["spec_template"],
        source_hint=raw["source_hint"],
        cadence=raw["cadence"],
        applicability=raw["applicability"],
        note=raw["note"],
    )


def load_proxy_library(path: str | None = None) -> list[ProxyEntry]:
    """加载并校验 proxy 备选库；任何问题一律抛 ProxyLibraryError（fail-closed）。

    Args:
        path: 显式 yaml 路径（config.proxy_library.path）；None = 包内默认资源。
    """
    text = _read_library_text(path)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ProxyLibraryError(f"proxy 备选库 yaml 解析失败: {e}") from e

    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ProxyLibraryError("proxy 备选库结构非法：顶层须为含 entries 列表的映射")
    raw_entries = data["entries"]
    if not raw_entries:
        raise ProxyLibraryError("proxy 备选库 entries 为空：不得空库运行")

    seen_ids: set[str] = set()
    return [_parse_entry(raw, i, seen_ids) for i, raw in enumerate(raw_entries)]


def render_s3_library_block(entries: list[ProxyEntry]) -> str:
    """逐条渲染为单行清单，按 id 排序（确定性：同一 yaml 两次渲染字节一致）。

    行格式：`- [Q01] 营收增速趋势（quantitative·引擎可算）：<spec>｜来源:<source>｜频率:<cadence>`
    """
    lines = []
    for e in sorted(entries, key=lambda x: x.id):
        capability = f"{e.type_hint}·引擎可算" if e.engine_computable else e.type_hint
        lines.append(
            f"- [{e.id}] {e.name}（{capability}）：{e.spec_template}"
            f"｜来源:{e.source_hint}｜频率:{e.cadence}"
        )
    return "\n".join(lines)
