"""
阶段产物持久化 (ArtifactStore)

把 S1–S5 每个阶段的产物（RefinedThesis / LogicChain / ProxyMapping / Evidence /
ThesisProjection）以 JSON 落盘，便于人工审查与回溯：

    <artifacts_dir>/<ticker>/<YYYY-MM-DD>/S{n}_<stage>.json

与 AuditReportStore（CSV 行式）解耦：本类只负责「可审查的证据链」产物，不影响
向后兼容的 AuditResult / CSV。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)

_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def _to_jsonable(artifact: Any) -> Any:
    """把 pydantic 模型 / 模型列表 / 普通结构转为可 JSON 序列化对象"""
    if isinstance(artifact, BaseModel):
        return artifact.model_dump(mode="json")
    if isinstance(artifact, (list, tuple)):
        return [_to_jsonable(x) for x in artifact]
    if isinstance(artifact, dict):
        return {k: _to_jsonable(v) for k, v in artifact.items()}
    return artifact


class ArtifactStore:
    """阶段产物 JSON 存储"""

    def __init__(self, base_dir: str | Path = "./output/artifacts"):
        self._base = Path(base_dir)

    @staticmethod
    def _safe(component: str) -> str:
        """清洗用于路径的片段（ticker 通常安全，US 代码偶有特殊字符）"""
        return _ILLEGAL.sub("_", str(component)) or "_"

    @staticmethod
    def _date_str(date: datetime | str | None) -> str:
        if date is None:
            return "unknown-date"
        if isinstance(date, datetime):
            return date.strftime("%Y-%m-%d")
        return str(date)[:10]

    def run_dir(self, ticker: str, date: datetime | str | None) -> Path:
        """某标的某日的产物目录"""
        return self._base / self._safe(ticker) / self._safe(self._date_str(date))

    def stage_path(
        self,
        ticker: str,
        date: datetime | str | None,
        stage: str,
        index: int | None = None,
    ) -> Path:
        fname = f"S{index}_{self._safe(stage)}.json" if index else f"{self._safe(stage)}.json"
        return self.run_dir(ticker, date) / fname

    def save_stage(
        self,
        ticker: str,
        date: datetime | str | None,
        stage: str,
        artifact: Any,
        index: int | None = None,
    ) -> Path:
        """持久化单个阶段产物，返回写入路径。"""
        path = self.stage_path(ticker, date, stage, index=index)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_to_jsonable(artifact), ensure_ascii=False, indent=2)
        path.write_text(payload, encoding="utf-8")
        return path

    def load_stage(
        self,
        ticker: str,
        date: datetime | str | None,
        stage: str,
        model_cls: Type[M] | None = None,
        index: int | None = None,
    ) -> Any:
        """读取阶段产物；给定 model_cls 则反序列化为该 pydantic 模型。"""
        path = self.stage_path(ticker, date, stage, index=index)
        text = path.read_text(encoding="utf-8")
        if model_cls is not None:
            return model_cls.model_validate_json(text)
        return json.loads(text)

    def list_stages(self, ticker: str, date: datetime | str | None) -> list[Path]:
        """列出某标的某日已持久化的产物文件（按文件名排序）。"""
        run_dir = self.run_dir(ticker, date)
        if not run_dir.exists():
            return []
        return sorted(run_dir.glob("*.json"))
