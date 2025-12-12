"""
CSV 报告写入器

输出格式符合 PRD 6.1 节定义的 audit_report.csv 规范
"""
from datetime import datetime
from pathlib import Path

from .base import AuditReportStore
from ..engines.gap_calculator import AuditResult


class CSVReportWriter(AuditReportStore):
    """CSV 格式的审计报告写入器"""

    # CSV 列定义（按 PRD 6.1 规范）
    CSV_COLUMNS: list[str] = [
        "Date",
        "Ticker",
        "Name",
        "Price",
        "Sentiment_Score",
        "Implied_Growth",
        "Our_Growth",
        "Gap",
        "Signal",
        "Key_Narrative",
    ]

    def __init__(self, file_path: str | Path = "audit_report.csv"):
        """
        初始化 CSV 写入器

        Args:
            file_path: CSV 文件路径
        """
        self._file_path = Path(file_path)

    def save(self, result: AuditResult) -> None:
        """
        保存单条审计结果（追加模式）

        Args:
            result: 审计结果
        """
        # TODO: 实现 CSV 追加写入
        # 1. 检查文件是否存在，不存在则创建并写入表头
        # 2. 将 AuditResult 转换为 CSV 行
        # 3. 追加写入
        raise NotImplementedError

    def save_batch(self, results: list[AuditResult]) -> None:
        """
        批量保存审计结果

        Args:
            results: 审计结果列表
        """
        for result in results:
            self.save(result)

    def get_by_ticker(
        self,
        ticker: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        """按标的查询"""
        # TODO: 实现 CSV 读取和过滤
        raise NotImplementedError

    def get_by_date(self, date: datetime) -> list[AuditResult]:
        """按日期查询"""
        # TODO: 实现 CSV 读取和过滤
        raise NotImplementedError

    def get_by_signal(
        self,
        signal: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        """按信号查询"""
        # TODO: 实现 CSV 读取和过滤
        raise NotImplementedError

    def get_latest(self, ticker: str) -> AuditResult | None:
        """获取最新结果"""
        # TODO: 实现读取
        raise NotImplementedError

    def _result_to_row(self, result: AuditResult) -> list[str]:
        """
        将 AuditResult 转换为 CSV 行

        Args:
            result: 审计结果

        Returns:
            list[str]: CSV 行数据
        """
        return [
            result.date.strftime("%Y-%m-%d"),
            result.ticker,
            result.name,
            str(result.price),
            str(result.sentiment_score),
            str(result.implied_growth),
            str(result.our_growth),
            str(result.gap),
            result.signal.value,
            result.key_narrative.replace(",", "，"),  # 避免 CSV 分隔符冲突
        ]

    def _ensure_file_exists(self) -> None:
        """确保 CSV 文件存在，不存在则创建并写入表头"""
        # TODO: 实现
        raise NotImplementedError
