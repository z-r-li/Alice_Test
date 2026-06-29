"""
SQLite 持久化（P2）。

本文件承载两类共用同一个 DB 文件的存储（D-20260629-1：决策日志 / 持仓 / 风控史 /
alpha 追踪统一落 SQLite）：

1. ``SQLiteStore`` —— S7 决策日志（CDX-2）的落点。`decision_log` + `decision_outcome`
   两表 + 方法 v0.1 完整可用；`position_history` / `alpha_track` 本期仅建 DDL（v0.2 写
   方法），提前留位避免二次迁移。源自已过 10 条单测的离线纯 stdlib 原型，逐字并入。

2. ``SQLiteReportStore`` —— 审计报告（`audit_report` 行式）的 SQLite 写出器，与
   ``CSVReportWriter`` 并列的另一种 ``AuditReportStore`` 后端。原为 ``NotImplementedError``
   桩，本次落地为可用实现（`audit_reports` 表）。

设计不变量（承接已合入纪律）：
- 幂等 upsert（决策按 ``decision_id``；报告按 ``(date, ticker)``）——同日重跑不产生重复行。
- point-in-time（v0.1 = **粗·存在性快照，非内容版本化**）：决策行带 ``created_at`` + ``asof_date``；
  ``get_decisions(asof=...)`` 复现「截至某日我们**记录过哪些 decision_id**」（IR=IC*sqrt(breadth)
  验证时钟，P0-5 的地基）。它只保证「这条决策当时是否已入账」，**不**保证「当时的内容是什么」——
  内容级 point-in-time 重放（versioned rows）显式留待 v0.2「真·回测 point-in-time 重放」。
- 结果 append-only：决策入账行不可变；重新评分 = 往 ``decision_outcome`` 追加一行（hit_rate / IC
  在聚合前按 decision 取**最新 final**，故 backfill / 修正多条 final 不会被重复计数）。
- 不编造（fail-closed）：未知字段留 ``NULL``，**绝不补 0.0**；与 PR-A（C1/C2）同纪律。
- 两个语义未拍的口径（``confidence_basis`` / ``ic_outcome_def``）存成 per-row 标签、**不写
  死在 schema**，使团队日后标准化 M4 时无需迁移表。
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .base import AuditReportStore
from ..engines.gap_calculator import AuditResult, AuditSignal

ISO = "%Y-%m-%dT%H:%M:%SZ"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime(ISO)


def _eod(date_str: str) -> str:
    """A YYYY-MM-DD asof means 'through the end of that day'."""
    return date_str if "T" in date_str else date_str + "T23:59:59Z"


# Enumerated labels for the two M4 open semantic questions (recommended default first).
CONFIDENCE_BASES = ("hit_prob", "outperform_prob", "interval_conf")
IC_OUTCOME_DEFS = ("price_excess_return", "revenue_profit_growth", "event_realized")
DEFAULT_CONFIDENCE_BASIS = "hit_prob"           # 命中概率 (待团队拍 M4)
DEFAULT_IC_OUTCOME_DEF = "price_excess_return"  # 股价超额 (待团队拍 M4)
VALID_ACTIONS = ("BUY", "ADD", "HOLD", "TRIM", "SELL", "WAIT")


@dataclass
class DecisionEntry:
    decision_id: str               # stable id, e.g. f"{ticker}-{asof_date}"
    asof_date: str                 # YYYY-MM-DD — point-in-time anchor
    ticker: str
    action: str                    # human S7 call; WAIT is logged too (breadth/calibration)
    market: Optional[str] = None       # CN/HK/US — sets benchmark + currency
    benchmark: Optional[str] = None    # 沪深300 / HSI / SPX ...
    currency: Optional[str] = None
    signal: Optional[str] = None       # engine OPPORTUNITY/OVERHEATED/WAIT
    suggested_weight: Optional[float] = None  # RiskEngine
    our_growth: Optional[float] = None
    implied_growth: Optional[float] = None
    gap: Optional[float] = None        # our_growth - implied_growth (the α 差值)
    our_alpha: Optional[float] = None
    thesis_summary: Optional[str] = None
    catalyst: Optional[str] = None
    horizon_days: Optional[int] = None
    confidence_pct: Optional[float] = None
    confidence_basis: str = DEFAULT_CONFIDENCE_BASIS
    falsification: Optional[str] = None       # 证伪条件 / S1 kill_criteria
    ic_outcome_def: str = DEFAULT_IC_OUTCOME_DEF
    source_artifact: Optional[str] = None     # AuditResult artifact path/hash (traceable)
    pipeline_commit: Optional[str] = None
    model_version: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None          # set on save if None


@dataclass
class OutcomeEntry:
    decision_id: str
    realized_value: Optional[float] = None
    realized_direction: Optional[int] = None   # +1 / 0 / -1
    hit: Optional[int] = None                   # 1 / 0 (thesis direction realized?)
    excess_return: Optional[float] = None       # vs benchmark — feeds IC
    horizon_label: Optional[str] = None         # "30d" / "final"
    is_final: int = 0
    observed_at: Optional[str] = None
    note: Optional[str] = None


_DECISION_COLS = [f.name for f in dataclasses.fields(DecisionEntry)]
_OUTCOME_COLS = [f.name for f in dataclasses.fields(OutcomeEntry)]


def _rank(xs: list[float]) -> list[float]:
    """Average-rank (ties shared) — for Spearman IC."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


class SQLiteStore:
    """One DB file for P2 persistence. v0.1 = decision log fully usable."""

    def __init__(self, path: str = ":memory:"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def _create_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS decision_log (
                decision_id      TEXT PRIMARY KEY,
                created_at       TEXT NOT NULL,
                asof_date        TEXT NOT NULL,
                ticker           TEXT NOT NULL,
                action           TEXT NOT NULL,
                market           TEXT,
                benchmark        TEXT,
                currency         TEXT,
                signal           TEXT,
                suggested_weight REAL,
                our_growth       REAL,
                implied_growth   REAL,
                gap              REAL,
                our_alpha        REAL,
                thesis_summary   TEXT,
                catalyst         TEXT,
                horizon_days     INTEGER,
                confidence_pct   REAL,
                confidence_basis TEXT,
                falsification    TEXT,
                ic_outcome_def   TEXT,
                source_artifact  TEXT,
                pipeline_commit  TEXT,
                model_version    TEXT,
                notes            TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_decision_asof    ON decision_log(asof_date);
            CREATE INDEX IF NOT EXISTS ix_decision_ticker  ON decision_log(ticker);
            CREATE INDEX IF NOT EXISTS ix_decision_created ON decision_log(created_at);

            CREATE TABLE IF NOT EXISTS decision_outcome (
                outcome_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id        TEXT NOT NULL REFERENCES decision_log(decision_id),
                observed_at        TEXT NOT NULL,
                horizon_label      TEXT,
                realized_value     REAL,
                realized_direction INTEGER,
                hit                INTEGER,
                excess_return      REAL,
                is_final           INTEGER NOT NULL DEFAULT 0,
                note               TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_outcome_decision ON decision_outcome(decision_id);

            -- v0.2 extension points (DDL only; methods are stubs)
            CREATE TABLE IF NOT EXISTS position_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, asof_date TEXT NOT NULL,
                ticker TEXT NOT NULL, weight REAL, cash REAL, note TEXT
            );
            CREATE TABLE IF NOT EXISTS alpha_track (
                id INTEGER PRIMARY KEY AUTOINCREMENT, asof_date TEXT NOT NULL,
                ticker TEXT NOT NULL, our_alpha REAL, market_alpha REAL, realized_excess REAL
            );
            """
        )
        self.conn.commit()

    # ---- validation (fail-closed discipline) -------------------------------
    @staticmethod
    def _validate(d: dict) -> None:
        if d["action"] not in VALID_ACTIONS:
            raise ValueError(f"action {d['action']!r} not in {VALID_ACTIONS}")
        if d["confidence_basis"] not in CONFIDENCE_BASES:
            raise ValueError(f"confidence_basis {d['confidence_basis']!r} invalid")
        if d["ic_outcome_def"] not in IC_OUTCOME_DEFS:
            raise ValueError(f"ic_outcome_def {d['ic_outcome_def']!r} invalid")
        cp = d.get("confidence_pct")
        if cp is not None and not (0.0 <= cp <= 100.0):
            raise ValueError(f"confidence_pct {cp} out of [0,100]")
        if len(d["asof_date"]) < 10:
            raise ValueError(f"asof_date {d['asof_date']!r} must be YYYY-MM-DD")

    # ---- decision log ------------------------------------------------------
    def save_decision(self, entry: DecisionEntry) -> str:
        d = asdict(entry)
        if not d.get("created_at"):
            d["created_at"] = _utcnow()
        self._validate(d)
        cols = _DECISION_COLS
        placeholders = ",".join(":" + c for c in cols)
        # 幂等 upsert：除主键外整列覆盖，但 **保留首次 created_at**——它是 point-in-time
        # 锚（get_decisions(asof=) 据此重建存在性快照）；同日重跑若刷新 created_at，会让旧决策在
        # 「原入账时刻 ~ 重跑时刻」之间从历史快照里凭空消失。
        # 注意（v0.1 边界）：整列覆盖在**跨 asof_date 改写一笔旧决策**时，会让 get_decisions(asof=)
        # 在「原入账 ~ 重处理」之间的快照返回该行的**最新**内容（非当时内容）。v0.1 主用例是
        # 「同交易日重跑幂等」（保持同一 asof_date，无此泄漏）；内容级 point-in-time = v0.2 versioned rows。
        _immutable = ("decision_id", "created_at")
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in _immutable)
        self.conn.execute(
            f"INSERT INTO decision_log ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(decision_id) DO UPDATE SET {updates}",
            d,
        )
        self.conn.commit()
        return entry.decision_id

    def save_decisions(self, entries: Iterable[DecisionEntry]) -> int:
        n = 0
        for e in entries:
            self.save_decision(e)
            n += 1
        return n

    def get_decision(self, decision_id: str) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM decision_log WHERE decision_id=?", (decision_id,)
        ).fetchone()
        return dict(r) if r else None

    def get_decisions(self, asof: Optional[str] = None, ticker: Optional[str] = None,
                      since: Optional[str] = None, until: Optional[str] = None) -> list[dict]:
        """决策日志查询。

        ``asof``（v0.1 语义，**粗·存在性快照，非内容版本化**）：按 ``created_at <= eod(asof)``
        过滤，复现「截至 asof 我们**记录过哪些 decision_id**」。它回答「这条决策在 asof 之前是否
        已入账」，**不**回答「它在 asof 当时的内容是什么」——若同一 decision_id 在更晚的日子被以
        不同内容重处理（跨 asof_date 改写旧决策），快照会返回该行**最新**的 action/gap/model。
        内容级 point-in-time 重放（versioned rows）显式留待 v0.2。``since`` / ``until`` 按
        ``asof_date`` 闭区间过滤决策日（与 ``asof`` 的 created_at 维度正交）。
        """
        q = "SELECT * FROM decision_log WHERE 1=1"
        p: list[Any] = []
        if asof:    # point-in-time: only what was LOGGED by end of asof day
            q += " AND created_at <= ?"; p.append(_eod(asof))
        if ticker:
            q += " AND ticker = ?"; p.append(ticker)
        if since:
            q += " AND asof_date >= ?"; p.append(since)
        if until:
            q += " AND asof_date <= ?"; p.append(until)
        q += " ORDER BY asof_date, ticker"
        return [dict(r) for r in self.conn.execute(q, p).fetchall()]

    # ---- outcomes ----------------------------------------------------------
    @staticmethod
    def _validate_outcome(d: dict) -> None:
        """fail-closed：拒绝越界的兑现值，避免污染 hit_rate / open 判定。

        hit / is_final 直接进命中率求和与「是否终态」判定，realized_direction 是有向标签——
        越界（如 hit=2 / is_final=3）必须在落库前拦截。
        """
        if d.get("hit") not in (None, 0, 1):
            raise ValueError(f"hit {d['hit']!r} must be 0/1/None")
        if d.get("is_final") not in (0, 1):
            raise ValueError(f"is_final {d['is_final']!r} must be 0/1")
        if d.get("realized_direction") not in (None, -1, 0, 1):
            raise ValueError(
                f"realized_direction {d.get('realized_direction')!r} must be -1/0/1/None"
            )

    def record_outcome(self, outcome: OutcomeEntry) -> int:
        d = asdict(outcome)
        if not d.get("observed_at"):
            d["observed_at"] = _utcnow()
        self._validate_outcome(d)
        cols = _OUTCOME_COLS
        cur = self.conn.execute(
            f"INSERT INTO decision_outcome ({','.join(cols)}) "
            f"VALUES ({','.join(':' + c for c in cols)})",
            d,
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_outcomes(self, decision_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM decision_outcome WHERE decision_id=? ORDER BY observed_at",
            (decision_id,),
        ).fetchall()]

    def get_open_decisions(self, asof: Optional[str] = None) -> list[dict]:
        """Decisions with no FINAL outcome (as of `asof`, if given).

        point-in-time：`asof` 同时约束**决策行本身**（created_at ≤ asof，未来才入账的决策
        不算当时的 open 决策）与终态判定（只看 asof 前的 final outcome）。
        """
        outer = ""
        sub = ""
        p: list[Any] = []
        if asof:
            eod = _eod(asof)
            outer = " AND d.created_at <= ?"
            sub = " AND o.observed_at <= ?"
            p = [eod, eod]
        return [dict(r) for r in self.conn.execute(
            "SELECT d.* FROM decision_log d WHERE 1=1" + outer +
            " AND NOT EXISTS ("
            "  SELECT 1 FROM decision_outcome o WHERE o.decision_id=d.decision_id "
            f"  AND o.is_final=1{sub}) ORDER BY d.asof_date, d.ticker",
            p,
        ).fetchall()]

    # ---- the P0-5 payoff: hit-rate + IC over resolved decisions -----------
    def hit_rate(self, since: Optional[str] = None, until: Optional[str] = None,
                 include_wait: bool = False) -> Optional[float]:
        """终态命中率；`since`/`until` 按决策的 ``asof_date`` 闭区间限定验证窗口
        （滚动 / 回测报告需要：否则窗口会被窗外的旧/新决策污染）。

        decision_outcome 是 append-only，同一 decision 可有多条 is_final=1（修正 / backfill）。
        故先按 ``MAX(outcome_id)``（自增、单调、无并列）取每 decision 的**最新 final**，再对那
        一行套 ``o.hit IS NOT NULL`` —— 若最新 final 的 hit 为 NULL，该 decision 整体剔除，
        **不回退**到更早 final（fail-closed / 不编造）。同理见 information_coefficient()；二者各自
        在「最新 final、本指标列非空」上取样，故当 NULL 落在不同列时入样集合可不同（非 bug）。"""
        q = ("SELECT d.action, o.hit FROM decision_log d "
             "JOIN decision_outcome o ON o.decision_id=d.decision_id "
             "WHERE o.is_final=1 AND o.hit IS NOT NULL "
             "AND o.outcome_id = ("
             "  SELECT MAX(o2.outcome_id) FROM decision_outcome o2 "
             "  WHERE o2.decision_id=d.decision_id AND o2.is_final=1)")
        p: list[Any] = []
        if since:
            q += " AND d.asof_date >= ?"; p.append(since)
        if until:
            q += " AND d.asof_date <= ?"; p.append(until)
        rows = self.conn.execute(q, p).fetchall()
        hits = [r["hit"] for r in rows
                if (include_wait or r["action"] != "WAIT")]
        return (sum(hits) / len(hits)) if hits else None

    def information_coefficient(self, predictor: str = "gap") -> Optional[float]:
        """Spearman rank-corr between the predictor (gap|confidence_pct|our_alpha)
        and realized excess_return over FINAL outcomes. IR = IC * sqrt(breadth)."""
        if predictor not in ("gap", "confidence_pct", "our_alpha"):
            raise ValueError("predictor must be gap|confidence_pct|our_alpha")
        # 与 hit_rate 同：append-only 下按 MAX(outcome_id) 取每 decision 的最新 final，再对那一行
        # 套 o.excess_return IS NOT NULL（最新 final 无收益值则该 decision 不进样本，不回退旧 final）。
        rows = self.conn.execute(
            f"SELECT d.{predictor} AS x, o.excess_return AS y FROM decision_log d "
            "JOIN decision_outcome o ON o.decision_id=d.decision_id "
            "WHERE o.is_final=1 AND o.excess_return IS NOT NULL AND d." + predictor + " IS NOT NULL "
            "AND o.outcome_id = ("
            "  SELECT MAX(o2.outcome_id) FROM decision_outcome o2 "
            "  WHERE o2.decision_id=d.decision_id AND o2.is_final=1)"
        ).fetchall()
        xs = [r["x"] for r in rows]
        ys = [r["y"] for r in rows]
        if len(xs) < 2:
            return None
        return _pearson(_rank(xs), _rank(ys))


class SQLiteReportStore(AuditReportStore):
    """审计报告的 SQLite 写出器（与 ``CSVReportWriter`` 并列的 ``AuditReportStore`` 后端）。

    与决策日志 ``SQLiteStore`` 共用同一个 DB 文件约定（D-20260629-1）：`audit_reports`
    表存逐标的审计行，按 ``(date, ticker)`` 幂等 upsert（同日重跑覆盖、不重复）。
    遵循「不编造」：缺字段 / NaN 如实存（NULL / NaN），读回不补看似真实的默认。
    """

    TABLE_NAME = "audit_reports"

    # 列顺序即 INSERT/SELECT 顺序；列名对齐 AuditResult 字段（list 字段以 JSON 文本存）。
    _COLUMNS: tuple[str, ...] = (
        "date", "ticker", "name", "price", "pe_ttm",
        "sentiment_score", "sentiment_label", "implied_growth",
        "key_narrative", "key_worry", "key_hope",
        "thesis_aligned", "our_growth", "confidence", "reasoning",
        "gap", "signal", "status", "needs_due_diligence",
        "artifact_dir", "evidence_summary",
        "suggested_weight", "correlation_flags", "structural_exit",
        "quant_exit_target", "risk_adjusted_action", "risk_contribution",
    )

    def __init__(self, db_path: str | Path = "audit_data.db"):
        """初始化 SQLite 存储并建表。

        Args:
            db_path: 数据库文件路径（``:memory:`` 走内存库，测试用）。
        """
        self._db_path = Path(db_path) if db_path != ":memory:" else db_path
        if isinstance(self._db_path, Path) and self._db_path.parent != Path(""):
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_table()

    def __enter__(self) -> "SQLiteReportStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def save(self, result: AuditResult) -> None:
        """保存单条审计结果（按 (date, ticker) 幂等 upsert）。"""
        d = self._result_to_row(result)
        cols = self._COLUMNS
        placeholders = ",".join(":" + c for c in cols)
        updates = ",".join(
            f"{c}=excluded.{c}" for c in cols if c not in ("date", "ticker")
        )
        self.conn.execute(
            f"INSERT INTO {self.TABLE_NAME} ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date, ticker) DO UPDATE SET {updates}",
            d,
        )
        self.conn.commit()

    def save_batch(self, results: list[AuditResult]) -> None:
        """批量保存（单事务）。"""
        for result in results:
            d = self._result_to_row(result)
            cols = self._COLUMNS
            placeholders = ",".join(":" + c for c in cols)
            updates = ",".join(
                f"{c}=excluded.{c}" for c in cols if c not in ("date", "ticker")
            )
            self.conn.execute(
                f"INSERT INTO {self.TABLE_NAME} ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(date, ticker) DO UPDATE SET {updates}",
                d,
            )
        self.conn.commit()

    def get_by_ticker(
        self,
        ticker: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        """按标的查询（可选起止日期，闭区间）。"""
        q = f"SELECT * FROM {self.TABLE_NAME} WHERE ticker = ?"
        p: list[Any] = [ticker]
        if start_date is not None:
            q += " AND date >= ?"; p.append(start_date.strftime("%Y-%m-%d"))
        if end_date is not None:
            q += " AND date <= ?"; p.append(end_date.strftime("%Y-%m-%d"))
        q += " ORDER BY date"
        return [self._row_to_result(r) for r in self.conn.execute(q, p).fetchall()]

    def get_by_date(self, date: datetime) -> list[AuditResult]:
        """按日期查询该日所有标的。"""
        rows = self.conn.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE date = ? ORDER BY ticker",
            (date.strftime("%Y-%m-%d"),),
        ).fetchall()
        return [self._row_to_result(r) for r in rows]

    def get_by_signal(
        self,
        signal: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        """按信号类型查询（可选起止日期）。"""
        q = f"SELECT * FROM {self.TABLE_NAME} WHERE signal = ?"
        p: list[Any] = [signal]
        if start_date is not None:
            q += " AND date >= ?"; p.append(start_date.strftime("%Y-%m-%d"))
        if end_date is not None:
            q += " AND date <= ?"; p.append(end_date.strftime("%Y-%m-%d"))
        q += " ORDER BY date, ticker"
        return [self._row_to_result(r) for r in self.conn.execute(q, p).fetchall()]

    def get_latest(self, ticker: str) -> AuditResult | None:
        """获取指定标的最新（date 最大）审计结果。"""
        r = self.conn.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        return self._row_to_result(r) if r else None

    # ---- (de)serialization --------------------------------------------------
    @staticmethod
    def _bool_to_int(value: bool | None) -> int | None:
        return None if value is None else int(value)

    @staticmethod
    def _list_to_json(value: list[str] | None) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _json_to_list(value: str | None) -> list[str] | None:
        if value is None:
            return None
        return [str(x) for x in json.loads(value)]

    def _result_to_row(self, result: AuditResult) -> dict[str, Any]:
        return {
            "date": result.date.strftime("%Y-%m-%d"),
            "ticker": result.ticker,
            "name": result.name,
            "price": result.price,
            "pe_ttm": result.pe_ttm,
            "sentiment_score": result.sentiment_score,
            "sentiment_label": result.sentiment_label,
            "implied_growth": result.implied_growth,
            "key_narrative": result.key_narrative,
            "key_worry": result.key_worry,
            "key_hope": result.key_hope,
            "thesis_aligned": self._bool_to_int(result.thesis_aligned),
            "our_growth": result.our_growth,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "gap": result.gap,
            "signal": result.signal.value,
            "status": getattr(result, "status", "ok"),
            "needs_due_diligence": self._bool_to_int(
                getattr(result, "needs_due_diligence", None)
            ),
            "artifact_dir": getattr(result, "artifact_dir", None),
            "evidence_summary": getattr(result, "evidence_summary", None),
            "suggested_weight": getattr(result, "suggested_weight", None),
            "correlation_flags": self._list_to_json(
                getattr(result, "correlation_flags", None)
            ),
            "structural_exit": self._list_to_json(
                getattr(result, "structural_exit", None)
            ),
            "quant_exit_target": getattr(result, "quant_exit_target", None),
            "risk_adjusted_action": getattr(result, "risk_adjusted_action", None),
            "risk_contribution": getattr(result, "risk_contribution", None),
        }

    def _row_to_result(self, row: sqlite3.Row) -> AuditResult:
        d = dict(row)
        return AuditResult(
            date=datetime.strptime(d["date"], "%Y-%m-%d"),
            ticker=d["ticker"],
            name=d["name"],
            price=d["price"],
            pe_ttm=d["pe_ttm"],
            sentiment_score=d["sentiment_score"],
            sentiment_label=d["sentiment_label"],
            implied_growth=d["implied_growth"],
            key_narrative=d["key_narrative"],
            key_worry=d["key_worry"],
            key_hope=d["key_hope"],
            thesis_aligned=bool(d["thesis_aligned"]) if d["thesis_aligned"] is not None else None,
            our_growth=d["our_growth"],
            confidence=d["confidence"],
            reasoning=d["reasoning"],
            gap=d["gap"],
            signal=AuditSignal(d["signal"]),
            status=d["status"],
            needs_due_diligence=(
                bool(d["needs_due_diligence"])
                if d["needs_due_diligence"] is not None
                else None
            ),
            artifact_dir=d["artifact_dir"],
            evidence_summary=d["evidence_summary"],
            suggested_weight=d["suggested_weight"],
            correlation_flags=self._json_to_list(d["correlation_flags"]),
            structural_exit=self._json_to_list(d["structural_exit"]),
            quant_exit_target=d["quant_exit_target"],
            risk_adjusted_action=d["risk_adjusted_action"],
            risk_contribution=d["risk_contribution"],
        )

    def _create_table(self) -> None:
        """创建 audit_reports 表（按 (date, ticker) 唯一约束，支持幂等 upsert）。"""
        self.conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                date                 TEXT NOT NULL,
                ticker               TEXT NOT NULL,
                name                 TEXT NOT NULL,
                price                REAL,
                pe_ttm               REAL,
                sentiment_score      INTEGER,
                sentiment_label      TEXT,
                implied_growth       REAL,
                key_narrative        TEXT,
                key_worry            TEXT,
                key_hope             TEXT,
                thesis_aligned       INTEGER,
                our_growth           REAL,
                confidence           TEXT,
                reasoning            TEXT,
                gap                  REAL,
                signal               TEXT NOT NULL,
                status               TEXT DEFAULT 'ok',
                needs_due_diligence  INTEGER,
                artifact_dir         TEXT,
                evidence_summary     TEXT,
                suggested_weight     REAL,
                correlation_flags    TEXT,
                structural_exit      TEXT,
                quant_exit_target    REAL,
                risk_adjusted_action TEXT,
                risk_contribution    REAL,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, ticker)
            );
            CREATE INDEX IF NOT EXISTS ix_report_ticker ON {self.TABLE_NAME}(ticker);
            CREATE INDEX IF NOT EXISTS ix_report_date   ON {self.TABLE_NAME}(date);
            CREATE INDEX IF NOT EXISTS ix_report_signal ON {self.TABLE_NAME}(signal);
            """
        )
        self.conn.commit()
