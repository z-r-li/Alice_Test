"""S6 RiskEngine v0.1 确定性单测（纯离线，无外部依赖）。

`risk_engine` 是自包含纯模块，本测试也刻意不依赖 pydantic / 数据栈：
优先常规包导入（你的 venv 里走这条），失败则按文件路径直接加载（沙箱/隔离环境）。
既可 `pytest tests/test_risk_engine.py`，也可 `python tests/test_risk_engine.py`。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

try:  # 常规：在装好依赖的 venv / CI 里
    from src.engines.risk_engine import (
        RiskEngine,
        RiskConfig,
        PortfolioState,
        OPPORTUNITY,
        OVERHEATED,
        WAIT,
        AVOID,
        SENTIMENT_OVERHEAT,
        UNKNOWN_CLUSTER,
    )
except Exception:  # 隔离/离线：把自包含模块作为顶层模块导入，绕过包 __init__（避免拖入数据栈）
    import sys
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "engines"))
    from risk_engine import (  # type: ignore[import-not-found]
        RiskEngine,
        RiskConfig,
        PortfolioState,
        OPPORTUNITY,
        OVERHEATED,
        WAIT,
        AVOID,
        SENTIMENT_OVERHEAT,
        UNKNOWN_CLUSTER,
    )

EPS = 1e-9


@dataclass
class FakeAudit:
    """AuditResult 的鸭子类型替身（只含 RiskEngine 用到的字段）。"""

    ticker: str
    signal: str = WAIT
    gap: float = 0.0
    thesis_aligned: bool = False
    our_growth: float = 0.0
    industry: str = UNKNOWN_CLUSTER
    sentiment_overheat: bool = False


def _opp(ticker: str, industry: str = UNKNOWN_CLUSTER, gap: float = 12.0) -> FakeAudit:
    return FakeAudit(ticker, signal=OPPORTUNITY, gap=gap, thesis_aligned=True,
                     our_growth=15.0, industry=industry)


def _assert_invariants(assessments, cfg: RiskConfig) -> None:
    """全局不变量：单笔 ≤ soft_cap、Σw ≤ total_risk_budget、同簇 ≤ cap。"""
    total = sum(a.suggested_weight for a in assessments)
    assert total <= cfg.total_risk_budget + EPS, total
    for a in assessments:
        assert a.suggested_weight >= -EPS
        assert a.suggested_weight <= cfg.soft_cap + EPS, (a.ticker, a.suggested_weight)


# --------------------------------------------------------------------------- #


def test_empty_portfolio_no_crash():
    assert RiskEngine().assess_portfolio([]) == []


def test_all_wait_gives_zero_weight():
    items = [FakeAudit("A.SH"), FakeAudit("B.SH"), FakeAudit("C.SH")]
    out = RiskEngine().assess_portfolio(items)
    assert len(out) == 3
    assert [a.ticker for a in out] == ["A.SH", "B.SH", "C.SH"]  # 顺序保持
    assert all(a.suggested_weight == 0.0 for a in out)
    assert all(a.risk_adjusted_action == WAIT for a in out)


def test_single_opportunity_gets_ref_weight():
    cfg = RiskConfig()  # ref 0.05, soft_cap 0.10
    out = RiskEngine(cfg).assess_portfolio([_opp("601985.SH", industry="电力")])
    assert math.isclose(out[0].suggested_weight, 0.05, abs_tol=EPS)
    assert out[0].risk_adjusted_action == "BUY"
    _assert_invariants(out, cfg)


def test_soft_cap_limits_single_name():
    cfg = RiskConfig(ref_weight=0.20, soft_cap=0.10)  # ref 高于护栏 → 被护栏压到 0.10
    out = RiskEngine(cfg).assess_portfolio([_opp("X.SH", industry="半导体")])
    assert math.isclose(out[0].suggested_weight, 0.10, abs_tol=EPS)
    _assert_invariants(out, cfg)


def test_thesis_misaligned_not_eligible():
    item = FakeAudit("Y.SH", signal=OPPORTUNITY, thesis_aligned=False, industry="电力")
    out = RiskEngine().assess_portfolio([item])
    assert out[0].suggested_weight == 0.0
    assert out[0].risk_adjusted_action == WAIT


def test_cluster_cap_scales_same_industry():
    cfg = RiskConfig(ref_weight=0.05, soft_cap=0.10, max_cluster_weight=0.15)
    names = ["P1.SH", "P2.SH", "P3.SH", "P4.SH"]
    out = RiskEngine(cfg).assess_portfolio([_opp(n, industry="电力") for n in names])
    cluster_total = sum(a.suggested_weight for a in out)
    assert cluster_total <= cfg.max_cluster_weight + EPS
    assert math.isclose(cluster_total, 0.15, abs_tol=1e-6)  # 0.20 → 缩到 0.15
    for a in out:  # 同簇互相 flag
        assert sorted(a.correlation_flags) == sorted(n for n in names if n != a.ticker)
    _assert_invariants(out, cfg)


def test_total_budget_scales_when_overcommitted():
    cfg = RiskConfig(ref_weight=0.30, soft_cap=0.30, max_cluster_weight=1.0,
                     total_risk_budget=1.0)
    # 5 个不同板块（单成员簇，不触发同簇上限），5×0.30=1.5 > 1.0 → 等比缩到 1.0
    items = [_opp(f"T{i}.SH", industry=f"板块{i}") for i in range(5)]
    out = RiskEngine(cfg).assess_portfolio(items)
    total = sum(a.suggested_weight for a in out)
    assert math.isclose(total, 1.0, abs_tol=1e-6)
    assert all(math.isclose(a.suggested_weight, 0.20, abs_tol=1e-6) for a in out)
    _assert_invariants(out, cfg)


def test_total_budget_not_exceeded_after_rounding():
    cfg = RiskConfig(
        ref_weight=0.01,
        soft_cap=0.01,
        max_cluster_weight=1.0,
        total_risk_budget=0.000002,
    )
    items = [_opp(f"R{i}.SH", industry=f"板块{i}") for i in range(3)]
    out = RiskEngine(cfg).assess_portfolio(items)

    assert sum(a.suggested_weight for a in out) <= cfg.total_risk_budget + EPS
    assert all(round(a.suggested_weight, 6) == a.suggested_weight for a in out)


def test_duplicate_ticker_not_folded_by_dict_key():
    cfg = RiskConfig(ref_weight=0.05, soft_cap=0.10, max_cluster_weight=1.0)
    items = [_opp("DUP.SH", industry="电力"), _opp("DUP.SH", industry="电力")]
    out = RiskEngine(cfg).assess_portfolio(items)

    assert len(out) == 2
    assert out[0] is not out[1]
    assert [a.ticker for a in out] == ["DUP.SH", "DUP.SH"]
    assert [a.suggested_weight for a in out] == [0.05, 0.05]
    assert out[0].correlation_flags == ["DUP.SH"]
    assert out[1].correlation_flags == ["DUP.SH"]


def test_unknown_cluster_exempt_from_cap_and_flags():
    cfg = RiskConfig(ref_weight=0.05, soft_cap=0.10, max_cluster_weight=0.15)
    # 4 个 UNKNOWN：合计 0.20 > 0.15，但 UNKNOWN 不当作真实簇 → 不缩、不互相 flag
    out = RiskEngine(cfg).assess_portfolio([_opp(f"U{i}.SH") for i in range(4)])
    assert all(math.isclose(a.suggested_weight, 0.05, abs_tol=EPS) for a in out)
    assert all(a.correlation_flags == [] for a in out)


def test_structural_exit_from_kill_criteria():
    kc = {"601985.SH": ["核电审批长期停滞", "电价市场化致 ROE 下行"]}
    out = RiskEngine().assess_portfolio([_opp("601985.SH", industry="电力")],
                                        kill_criteria_by_ticker=kc)
    assert out[0].structural_exit == kc["601985.SH"]


def test_quant_exit_target_deferred_none():
    out = RiskEngine().assess_portfolio([_opp("A.SH", industry="电力")])
    assert out[0].quant_exit_target is None  # D3 待定


def test_assess_one_structural_exit_and_action():
    eng = RiskEngine()
    ra = eng.assess_one(_opp("Z.SH", industry="电力"), kill_criteria=["护城河瓦解", " "])
    assert ra.structural_exit == ["护城河瓦解"]  # 空白项被过滤
    assert ra.risk_adjusted_action == "BUY"
    assert eng.assess_one(FakeAudit("W.SH")).risk_adjusted_action == WAIT


# ---- 信号语义 v2（D-20260705-1）：OVERHEATED → AVOID + weight 0 + flag 透传 ---- #


def test_overheated_gets_avoid_with_zero_weight():
    """OVERHEATED（负 α）→ AVOID、weight=0；不占预算、不进簇 flag。"""
    items = [
        FakeAudit("HOT.SH", signal=OVERHEATED, gap=-15.0, thesis_aligned=True,
                  industry="半导体"),
        _opp("OK.SH", industry="电力"),
    ]
    out = RiskEngine().assess_portfolio(items)
    hot, ok = out
    assert hot.risk_adjusted_action == AVOID
    assert hot.suggested_weight == 0.0
    assert hot.correlation_flags == []           # 不合格 → 不参与聚类 flag
    assert ok.risk_adjusted_action == "BUY"      # 邻座不受影响
    assert math.isclose(ok.suggested_weight, 0.05, abs_tol=EPS)


def test_overheated_not_eligible_for_buy_gate():
    """_eligible（BUY 门）不动：OVERHEATED 即便 thesis_aligned 也绝不 BUY。"""
    item = FakeAudit("HOT.SH", signal=OVERHEATED, gap=-20.0, thesis_aligned=True)
    assert RiskEngine()._eligible(item) is False
    out = RiskEngine().assess_portfolio([item])
    assert out[0].risk_adjusted_action == AVOID


def test_assess_one_overheated_avoid():
    """单标的路径同口径：assess_one 对 OVERHEATED 产 AVOID。"""
    eng = RiskEngine()
    ra = eng.assess_one(FakeAudit("HOT.SH", signal=OVERHEATED, gap=-12.0))
    assert ra.risk_adjusted_action == AVOID
    assert ra.suggested_weight == 0.0


def test_sentiment_overheat_flag_appended():
    """sentiment_overheat=True → correlation_flags 追加 SENTIMENT_OVERHEAT（只登记，不折减权重）。"""
    items = [
        _opp("A.SH", industry="电力"),
        FakeAudit("B.SH", signal=OPPORTUNITY, gap=12.0, thesis_aligned=True,
                  our_growth=15.0, industry="电力", sentiment_overheat=True),
        FakeAudit("C.SH", signal=OVERHEATED, gap=-15.0, sentiment_overheat=True),
    ]
    out = RiskEngine().assess_portfolio(items)
    a, b, c = out
    assert SENTIMENT_OVERHEAT not in a.correlation_flags
    assert SENTIMENT_OVERHEAT in b.correlation_flags
    assert "A.SH" in b.correlation_flags          # 簇 flag 与情绪 flag 并存
    assert SENTIMENT_OVERHEAT in c.correlation_flags
    # 不折减：B 权重与无 flag 的 A 相同（折减系数未拍，登记即止）
    assert math.isclose(b.suggested_weight, a.suggested_weight, abs_tol=EPS)


def test_industry_map_param_when_no_attr():
    @dataclass
    class Bare:  # 没有 industry 属性 → 用传入的 industry_by_ticker
        ticker: str
        signal: str = OPPORTUNITY
        gap: float = 12.0
        thesis_aligned: bool = True
        our_growth: float = 10.0

    cfg = RiskConfig(max_cluster_weight=0.15)
    items = [Bare(f"B{i}.SH") for i in range(4)]
    ind = {f"B{i}.SH": "银行" for i in range(4)}
    out = RiskEngine(cfg).assess_portfolio(items, industry_by_ticker=ind)
    assert sum(a.suggested_weight for a in out) <= cfg.max_cluster_weight + EPS


# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
        passed += 1
    print(f"\n[done] {passed}/{len(fns)} passed")
