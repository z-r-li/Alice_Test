"""
SQLite 存储实现（预留接口）

为后续扩展准备，当前为空实现
"""
from datetime import datetime
from pathlib import Path

from .base import AuditReportStore
from ..engines.gap_calculator import AuditResult


class SQLiteReportStore(AuditReportStore):
    """SQLite 存储实现（预留）"""

    TABLE_NAME = "audit_reports"

    def __init__(self, db_path: str | Path = "audit_data.db"):
        """
        初始化 SQLite 存储

        Args:
            db_path: 数据库文件路径
        """
        self._db_path = Path(db_path)
        # TODO: 初始化数据库连接
        # TODO: 创建表结构

    def save(self, result: AuditResult) -> None:
        """保存单条审计结果"""
        # TODO: INSERT INTO audit_reports ...
        raise NotImplementedError

    def save_batch(self, results: list[AuditResult]) -> None:
        """批量保存"""
        # TODO: 使用事务批量插入
        raise NotImplementedError

    def get_by_ticker(
        self,
        ticker: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        """按标的查询"""
        # TODO: SELECT * FROM audit_reports WHERE ticker = ? AND ...
        raise NotImplementedError

    def get_by_date(self, date: datetime) -> list[AuditResult]:
        """按日期查询"""
        # TODO: SELECT * FROM audit_reports WHERE date = ?
        raise NotImplementedError

    def get_by_signal(
        self,
        signal: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        """按信号查询"""
        # TODO: SELECT * FROM audit_reports WHERE signal = ? AND ...
        raise NotImplementedError

    def get_latest(self, ticker: str) -> AuditResult | None:
        """获取最新结果"""
        # TODO: SELECT * FROM audit_reports WHERE ticker = ? ORDER BY date DESC LIMIT 1
        raise NotImplementedError

    def _create_table(self) -> None:
        """
        创建表结构

        Schema:
            CREATE TABLE IF NOT EXISTS audit_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                sentiment_score INTEGER NOT NULL,
                implied_growth REAL NOT NULL,
                our_growth REAL NOT NULL,
                gap REAL NOT NULL,
                signal TEXT NOT NULL,
                key_narrative TEXT,
                reasoning TEXT,
                status TEXT DEFAULT 'ok',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, ticker)
            );
        """
        raise NotImplementedError
