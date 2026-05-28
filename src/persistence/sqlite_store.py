"""SQLite 审计报告存储实现。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .base import AuditReportStore
from ..engines.gap_calculator import AuditResult, AuditSignal


class SQLiteReportStore(AuditReportStore):
    """SQLite 审计报告存储。

    表 `audit_reports` 以 (date, ticker) 作为唯一约束 — 同一标的同一天
    重复写入会用 INSERT OR REPLACE 覆盖旧记录。
    """

    TABLE_NAME = "audit_reports"
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS audit_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        pe_ttm REAL,
        sentiment_score INTEGER NOT NULL,
        sentiment_label TEXT NOT NULL,
        implied_growth REAL NOT NULL,
        key_narrative TEXT NOT NULL,
        key_worry TEXT NOT NULL,
        key_hope TEXT NOT NULL,
        thesis_aligned INTEGER NOT NULL,
        our_growth REAL NOT NULL,
        confidence TEXT NOT NULL,
        reasoning TEXT NOT NULL,
        gap REAL NOT NULL,
        signal TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, ticker)
    )
    """

    def __init__(self, db_path: str | Path = "audit_data.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(self._SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, result: AuditResult) -> None:
        with self._connect() as conn:
            self._insert(conn, result)
            conn.commit()

    def save_batch(self, results: list[AuditResult]) -> None:
        with self._connect() as conn:
            for r in results:
                self._insert(conn, r)
            conn.commit()

    @staticmethod
    def _insert(conn: sqlite3.Connection, r: AuditResult) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO audit_reports (
                date, ticker, name, price, pe_ttm,
                sentiment_score, sentiment_label, implied_growth,
                key_narrative, key_worry, key_hope,
                thesis_aligned, our_growth, confidence, reasoning,
                gap, signal, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.date.strftime("%Y-%m-%d"),
                r.ticker,
                r.name,
                r.price,
                r.pe_ttm,
                r.sentiment_score,
                r.sentiment_label,
                r.implied_growth,
                r.key_narrative,
                r.key_worry,
                r.key_hope,
                1 if r.thesis_aligned else 0,
                r.our_growth,
                r.confidence,
                r.reasoning,
                r.gap,
                r.signal.value,
                r.status,
            ),
        )

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> AuditResult:
        return AuditResult(
            date=datetime.strptime(row["date"], "%Y-%m-%d"),
            ticker=row["ticker"],
            name=row["name"],
            price=row["price"],
            pe_ttm=row["pe_ttm"],
            sentiment_score=row["sentiment_score"],
            sentiment_label=row["sentiment_label"],
            implied_growth=row["implied_growth"],
            key_narrative=row["key_narrative"],
            key_worry=row["key_worry"],
            key_hope=row["key_hope"],
            thesis_aligned=bool(row["thesis_aligned"]),
            our_growth=row["our_growth"],
            confidence=row["confidence"],
            reasoning=row["reasoning"],
            gap=row["gap"],
            signal=AuditSignal(row["signal"]),
            status=row["status"],
        )

    def get_by_ticker(
        self,
        ticker: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        sql = "SELECT * FROM audit_reports WHERE ticker = ?"
        params: list = [ticker]
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date.strftime("%Y-%m-%d"))
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date.strftime("%Y-%m-%d"))
        sql += " ORDER BY date"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_result(r) for r in rows]

    def get_by_date(self, date: datetime) -> list[AuditResult]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_reports WHERE date = ?",
                (date.strftime("%Y-%m-%d"),),
            ).fetchall()
        return [self._row_to_result(r) for r in rows]

    def get_by_signal(
        self,
        signal: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        sql = "SELECT * FROM audit_reports WHERE signal = ?"
        params: list = [signal]
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date.strftime("%Y-%m-%d"))
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date.strftime("%Y-%m-%d"))
        sql += " ORDER BY date"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_result(r) for r in rows]

    def get_latest(self, ticker: str) -> AuditResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM audit_reports WHERE ticker = ? ORDER BY date DESC LIMIT 1",
                (ticker,),
            ).fetchone()
        return self._row_to_result(row) if row else None
