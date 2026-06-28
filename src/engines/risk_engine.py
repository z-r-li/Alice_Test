"""S6 风险与组合叠加引擎 (RiskEngine) —— v0.1 离线骨架。

设计见 `新小道/小道项目_S6_RiskEngine设计说明_v0.1_20260627.md`（团队内部，未入库）。

定位：流水线缺失的「第三条腿」。在 S5 认知差信号之上，叠加**组合层风控**——
仓位 sizing、相关性/聚类、双路退出（结构性 + 量化）。

工程原则（本模块刻意为之）：
- **纯函数 / 纯数学**：无 IO、无 LLM、无网络、无 repo 重依赖（不 import pydantic /
  akshare / data_ingestion / llm），可独立、确定性单测，且方便将来（方案 A）抽成独立组合服务。
- 与 `AuditResult` 通过**鸭子类型**对接（见 `AuditLike`）：读 `ticker/signal/gap/
  thesis_aligned/our_growth`，不强依赖其类型；真正的接线在 `main.py`（循环后调用）。

本版（v0.1，不依赖 6/28 会议 D1–D5 的部分）已实现：
- 数据模型 `RiskConfig` / `PortfolioState` / `RiskAssessment`
- 结构性退出：复用 S1 `kill_criteria`（由调用方从 `ThesisProjection` 传入）
- 行业/簇聚类 flags + 同簇合计权重上限
- 「等权软参考 + 软护栏 + 整体风险预算」sizing（对应 D1 的 A 选项占位）

留待会议后（D1–D5 定了再写）：
- D1 信念加权 / 风险贡献 sizing（`sizing_mode` 预留）
- D3 量化退出目标 `quant_exit_target`（需 S4 forward PE/PEG）→ 现留 None
- D4 `PortfolioState` 持久化（现 greenfield，`state` 可选默认空）
- D2 真·相关性矩阵（需历史行情）→ 现用行业聚类近似
- 接线 `main.py` + 扩展 `AuditResult` 字段 + 持久化列
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol, runtime_checkable

__all__ = [
    "RiskConfig",
    "RiskAssessment",
    "PortfolioState",
    "RiskEngine",
    "OPPORTUNITY",
    "OVERHEATED",
    "WAIT",
    "UNKNOWN_CLUSTER",
]

# 信号字符串（与 gap_calculator.AuditSignal 的 .value 对齐；此处用裸串避免引入依赖）
OPPORTUNITY = "OPPORTUNITY"
OVERHEATED = "OVERHEATED"
WAIT = "WAIT"

UNKNOWN_CLUSTER = "UNKNOWN"  # 无已知行业/簇：不参与相关性假设与同簇上限


def _signal_str(sig: object) -> str:
    """AuditSignal(str, Enum) 或裸字符串 → 规范字符串。"""
    return getattr(sig, "value", sig) if sig is not None else ""


@runtime_checkable
class AuditLike(Protocol):
    """RiskEngine 读取的 `AuditResult` 子集（鸭子类型，避免引入 repo 重依赖）。"""

    ticker: str
    signal: object  # AuditSignal | str
    gap: float
    thesis_aligned: bool
    our_growth: float


@dataclass
class RiskConfig:
    """风控配置（会上 D1 定后再扩 sizing_mode；阈值均可在 config.yaml 覆盖）。"""

    ref_weight: float = 0.05          # 单笔软参考权重（非硬顶）
    soft_cap: float = 0.10            # 单笔软护栏（可被风险预算进一步压低）
    target_positions: int = 20        # 目标持仓数（~20 × 5% ≈ 满仓）
    max_cluster_weight: float = 0.15  # 同簇（行业/主题）合计权重上限
    total_risk_budget: float = 1.00   # 组合总投入上限（1.0=可满仓；预留现金 = 1 - Σw）
    sizing_mode: str = "equal"        # v0.1 占位；D1 后加 "conviction" / "risk_budget"
    enabled: bool = True


@dataclass
class RiskAssessment:
    """单标的的组合层风控结论（回填进 AuditResult / 落库）。"""

    ticker: str
    suggested_weight: float = 0.0                 # 建议仓位；~ref_weight 为软参考、非硬顶
    correlation_flags: list[str] = field(default_factory=list)  # 同簇/高相关的其他 ticker
    structural_exit: list[str] = field(default_factory=list)    # 结构性退出触发（来自 S1 kill_criteria）
    quant_exit_target: float | None = None        # 量化退出目标价/估值（D3 待定，v0.1 留空）
    risk_adjusted_action: str = WAIT              # BUY / TRIM / WAIT / EXIT
    risk_contribution: float | None = None        # 对组合总风险的贡献（v0.2 接相关阵后算）
    notes: str = ""


@dataclass
class PortfolioState:
    """组合状态（v0.1 默认空 = greenfield；D4 决定持久化落点后再接来源）。"""

    positions: dict[str, float] = field(default_factory=dict)   # ticker -> 当前权重
    clusters: dict[str, str] = field(default_factory=dict)      # ticker -> 簇/行业
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)  # v0.2
    cash: float = 1.0


class RiskEngine:
    """组合层风控引擎。无状态、纯函数；可在 main.py 循环后对整批结果调用。"""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    # ---------- 单标的：结构性退出 + 资格（不含跨标的 sizing） ----------
    def assess_one(
        self, item: AuditLike, kill_criteria: Iterable[str] | None = None
    ) -> RiskAssessment:
        """逐标的部分（在 main.py 的 per-ticker 循环内调用，此时 ThesisProjection 在作用域）。

        结构性退出直接复用 S1 `kill_criteria`（pipeline 已产出）。
        实际仓位由 `assess_portfolio` 在跨标的归一化时给出，这里只标资格。
        """
        ra = RiskAssessment(ticker=item.ticker)
        ra.structural_exit = [s for s in (kill_criteria or []) if str(s).strip()]
        ra.quant_exit_target = None  # D3 待定
        ra.risk_adjusted_action = "BUY" if self._eligible(item) else WAIT
        return ra

    # ---------- 组合层：聚类 + 整体风险预算下的 sizing，回填 ----------
    def assess_portfolio(
        self,
        items: Iterable[AuditLike],
        state: PortfolioState | None = None,
        kill_criteria_by_ticker: Mapping[str, Iterable[str]] | None = None,
        industry_by_ticker: Mapping[str, str] | None = None,
    ) -> list[RiskAssessment]:
        """对整批标的做组合层叠加，返回与输入同序的 RiskAssessment 列表。

        v0.1 sizing = 等权软参考 → 同簇上限 → 整体风险预算（均为「只减不增」缩放，
        故天然满足：单笔 ≤ soft_cap、同簇 ≤ max_cluster_weight、Σw ≤ total_risk_budget）。
        空机会集/全 WAIT 时优雅返回全 0、动作 WAIT，不报错。
        """
        cfg = self.config
        state = state or PortfolioState()
        kc = dict(kill_criteria_by_ticker or {})
        ind = dict(industry_by_ticker or {})
        items = list(items)

        def cluster_of(it: AuditLike) -> str:
            return (
                getattr(it, "industry", None)
                or ind.get(it.ticker)
                or state.clusters.get(it.ticker)
                or UNKNOWN_CLUSTER
            )

        out: list[RiskAssessment] = [
            RiskAssessment(
                ticker=it.ticker,
                structural_exit=[s for s in kc.get(it.ticker, []) if str(s).strip()],
            )
            for it in items
        ]

        eligible = [(i, it) for i, it in enumerate(items) if self._eligible(it)]
        clusters = {i: cluster_of(it) for i, it in eligible}

        # 1) 基线等权（软参考，受单笔软护栏约束）
        weights = {i: min(cfg.ref_weight, cfg.soft_cap) for i, _ in eligible}
        # 2) 同簇合计上限（UNKNOWN 不视为真实簇，跳过）
        weights = self._apply_cluster_cap(weights, clusters, cfg.max_cluster_weight)
        # 3) 整体风险预算：Σw ≤ total_risk_budget
        weights = self._apply_total_budget(weights, cfg.total_risk_budget)
        weights = self._round_weights_with_budget(weights, cfg.total_risk_budget)

        # 4) 回填
        for i, it in eligible:
            ra = out[i]
            ra.suggested_weight = weights.get(i, 0.0)
            cl = clusters[i]
            if cl != UNKNOWN_CLUSTER:
                ra.correlation_flags = sorted(
                    items[j].ticker for j, c in clusters.items() if c == cl and j != i
                )
            ra.risk_adjusted_action = "BUY" if ra.suggested_weight > 0 else WAIT
        for i, it in enumerate(items):
            if not self._eligible(it):
                out[i].risk_adjusted_action = WAIT

        return out

    # ---------- helpers ----------
    def _eligible(self, item: AuditLike) -> bool:
        return _signal_str(getattr(item, "signal", None)) == OPPORTUNITY and bool(
            getattr(item, "thesis_aligned", False)
        )

    @staticmethod
    def _apply_cluster_cap(
        weights: dict[int, float], clusters: Mapping[int, str], cap: float
    ) -> dict[int, float]:
        by_cluster: dict[str, list[int]] = {}
        for t in weights:
            cl = clusters.get(t, UNKNOWN_CLUSTER)
            if cl == UNKNOWN_CLUSTER:
                continue
            by_cluster.setdefault(cl, []).append(t)
        out = dict(weights)
        for members in by_cluster.values():
            tot = sum(out[t] for t in members)
            if tot > cap and tot > 0:
                scale = cap / tot
                for t in members:
                    out[t] *= scale
        return out

    @staticmethod
    def _apply_total_budget(weights: dict[int, float], budget: float) -> dict[int, float]:
        tot = sum(weights.values())
        if tot > budget and tot > 0:
            scale = budget / tot
            return {t: w * scale for t, w in weights.items()}
        return dict(weights)

    @staticmethod
    def _round_weights_with_budget(
        weights: dict[int, float], budget: float, decimals: int = 6
    ) -> dict[int, float]:
        """Round weights while preserving Σw <= budget."""
        rounded = {t: round(w, decimals) for t, w in weights.items()}
        if sum(rounded.values()) <= budget:
            return rounded

        unit = 10 ** -decimals
        # Repeatedly trim one rounding unit from the largest weights until within budget.
        while sum(rounded.values()) > budget:
            candidates = [t for t, w in rounded.items() if w > 0]
            if not candidates:
                break
            t = max(candidates, key=lambda key: (rounded[key], -key))
            rounded[t] = round(max(0.0, rounded[t] - unit), decimals)

            # Guard against pathological non-finite budgets/weights in direct dataclass use.
            if not math.isfinite(sum(rounded.values())):
                return {k: 0.0 for k in rounded}
        return rounded
