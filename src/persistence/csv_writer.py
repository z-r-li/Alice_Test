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

    # CSV 列定义（PRD 6.1 字段 + Module B 字段以保证读写无损）
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
        # Module B 字段（PRD 之外，用于回读时保留完整 AuditResult）
        "thesis_aligned",
        "confidence",
        "reasoning",
        "status",
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

    def _result_to_row(self, result: AuditResult) -> list[str]:
        """
        将 AuditResult 转换为 CSV 行

        Args:
            result: 审计结果

        Returns:
            list[str]: CSV 行数据
        """
        # 让 csv.writer 处理逗号与引号转义；不再手动替换逗号。
        return [
            result.date.strftime("%Y-%m-%d"),
            result.ticker,
            result.name,
            str(result.price),
            str(result.pe_ttm) if result.pe_ttm is not None else "",
            str(result.sentiment_score),
            result.sentiment_label,
            str(result.implied_growth),
            str(result.our_growth),
            str(result.gap),
            result.signal.value,
            result.key_narrative,
            result.key_worry,
            result.key_hope,
            "1" if result.thesis_aligned else "0",
            result.confidence,
            result.reasoning,
            result.status,
        ]

    def _row_to_result(self, row: dict[str, str]) -> AuditResult:
        """
        将 CSV 行（按列名映射的字典）转换为 AuditResult。

        Args:
            row: 由 csv.DictReader 生成的字典

        Returns:
            AuditResult: 审计结果对象
        """
        return AuditResult(
            date=datetime.strptime(row["date"], "%Y-%m-%d"),
            ticker=row["ticker"],
            name=row["name"],
            price=float(row["price"]),
            pe_ttm=float(row["pe_ttm"]) if row.get("pe_ttm") else None,
            sentiment_score=int(row["sentiment_score"]),
            sentiment_label=row["sentiment_label"],
            implied_growth=float(row["implied_growth"]),
            our_growth=float(row["our_growth"]),
            gap=float(row["gap"]),
            signal=AuditSignal(row["signal"]),
            key_narrative=row["key_narrative"],
            key_worry=row["key_worry"],
            key_hope=row["key_hope"],
            # 新字段：若旧 CSV 缺失则回退到合理默认
            thesis_aligned=row.get("thesis_aligned", "1") in ("1", "True", "true"),
            confidence=row.get("confidence") or "中",
            reasoning=row.get("reasoning") or "",
            status=row.get("status") or "ok",
        )

    def _read_all_results(self) -> list[AuditResult]:
        """
        读取 CSV 文件中的所有审计结果。

        通过 DictReader 按列名读取，支持旧版本 CSV（缺失新增列时回退默认）。

        Returns:
            list[AuditResult]: 所有审计结果列表
        """
        if not self._file_path.exists():
            return []

        results: list[AuditResult] = []
        with open(self._file_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("date"):
                    continue
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
