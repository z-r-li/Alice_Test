"""
CSV 报告写入器

输出格式符合 PRD 6.1 节定义的 audit_report.csv 规范
"""
import csv
from datetime import datetime
from pathlib import Path

from .base import AuditReportStore
from ..engines.gap_calculator import AuditResult, AuditSignal


class CSVReportWriter(AuditReportStore):
    """CSV 格式的审计报告写入器"""

    # CSV 列定义（按 PRD 6.1 规范）
    CSV_COLUMNS: list[str] = [
        "date",
        "ticker",
        "name",
        "price",
        "pe_ttm",
        "sentiment_score",
        "sentiment_label",
        "implied_growth",
        "our_growth",
        "gap",
        "signal",
        "key_narrative",
        "key_worry",
        "key_hope",
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
        # 确保文件存在（首次写入时创建并写入表头）
        self._ensure_file_exists()

        # 将 AuditResult 转换为 CSV 行并追加写入
        with open(self._file_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self._result_to_row(result))

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
        """
        按标的代码查询审计结果

        Args:
            ticker: 证券代码
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            list[AuditResult]: 审计结果列表
        """
        results = self._read_all_results()
        filtered = [r for r in results if r.ticker == ticker]

        if start_date:
            filtered = [r for r in filtered if r.date >= start_date]
        if end_date:
            filtered = [r for r in filtered if r.date <= end_date]

        return filtered

    def get_by_date(self, date: datetime) -> list[AuditResult]:
        """
        按日期查询所有标的审计结果

        Args:
            date: 审计日期

        Returns:
            list[AuditResult]: 该日所有审计结果
        """
        results = self._read_all_results()
        target_date = date.date() if hasattr(date, "date") else date
        return [
            r for r in results
            if r.date.date() == target_date
        ]

    def get_by_signal(
        self,
        signal: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[AuditResult]:
        """
        按信号类型查询

        Args:
            signal: 信号类型 ("OPPORTUNITY", "OVERHEATED", "WAIT")
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            list[AuditResult]: 匹配的审计结果
        """
        results = self._read_all_results()
        filtered = [r for r in results if r.signal.value == signal]

        if start_date:
            filtered = [r for r in filtered if r.date >= start_date]
        if end_date:
            filtered = [r for r in filtered if r.date <= end_date]

        return filtered

    def get_latest(self, ticker: str) -> AuditResult | None:
        """
        获取指定标的最新审计结果

        Args:
            ticker: 证券代码

        Returns:
            AuditResult | None: 最新结果或 None
        """
        results = self.get_by_ticker(ticker)
        if not results:
            return None
        # 按日期排序，返回最新的
        return max(results, key=lambda r: r.date)

    def _escape_comma(self, text: str) -> str:
        """将英文逗号替换为中文逗号，避免 CSV 分隔符冲突"""
        return text.replace(",", "，") if text else ""

    def _result_to_row(self, result: AuditResult) -> list[str]:
        """
        将 AuditResult 转换为 CSV 行

        Args:
            result: 审计结果

        Returns:
            list[str]: CSV 行数据（按 PRD 6.1 顺序）
        """
        return [
            result.date.strftime("%Y-%m-%d"),
            result.ticker,
            self._escape_comma(result.name),
            str(result.price),
            str(result.pe_ttm) if result.pe_ttm is not None else "",
            str(result.sentiment_score),
            result.sentiment_label,
            str(result.implied_growth),
            str(result.our_growth),
            str(result.gap),
            result.signal.value,
            self._escape_comma(result.key_narrative),
            self._escape_comma(result.key_worry),
            self._escape_comma(result.key_hope),
        ]

    def _row_to_result(self, row: list[str]) -> AuditResult:
        """
        将 CSV 行转换为 AuditResult

        Args:
            row: CSV 行数据

        Returns:
            AuditResult: 审计结果对象
        """
        return AuditResult(
            date=datetime.strptime(row[0], "%Y-%m-%d"),
            ticker=row[1],
            name=row[2],
            price=float(row[3]),
            pe_ttm=float(row[4]) if row[4] else None,
            sentiment_score=int(row[5]),
            sentiment_label=row[6],
            implied_growth=float(row[7]),
            our_growth=float(row[8]),
            gap=float(row[9]),
            signal=AuditSignal(row[10]),
            key_narrative=row[11],
            key_worry=row[12],
            key_hope=row[13],
            # 以下字段在 CSV 中不存储，使用默认值
            thesis_aligned=True,
            confidence="中",
            reasoning="",
        )

    def _read_all_results(self) -> list[AuditResult]:
        """
        读取 CSV 文件中的所有审计结果

        Returns:
            list[AuditResult]: 所有审计结果列表
        """
        if not self._file_path.exists():
            return []

        results = []
        with open(self._file_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            # 跳过表头
            next(reader, None)
            for row in reader:
                if len(row) >= 14:  # 确保行数据完整
                    results.append(self._row_to_result(row))
        return results

    def _ensure_file_exists(self) -> None:
        """确保 CSV 文件存在，不存在则创建并写入表头"""
        if self._file_path.exists():
            return

        # 创建父目录（如果不存在）
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建文件并写入表头
        with open(self._file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self.CSV_COLUMNS)
