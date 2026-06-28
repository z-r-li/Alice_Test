"""
CSV 报告写入器

输出格式符合 PRD 6.1 节定义的 audit_report.csv 规范
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

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
        "status",
        "needs_due_diligence",
        "suggested_weight",
        "correlation_flags",
        "structural_exit",
        "quant_exit_target",
        "risk_adjusted_action",
        "risk_contribution",
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

    @staticmethod
    def _serialize_list(value: list[str] | None) -> str:
        """Serialize list fields without inventing defaults for missing values."""
        if value is None:
            return ""
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _serialize_optional(value: object) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def _serialize_bool(value: bool | None) -> str:
        if value is None:
            return ""
        return "true" if value else "false"

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
            getattr(result, "status", "") or "",
            self._serialize_bool(getattr(result, "needs_due_diligence", None)),
            self._serialize_optional(getattr(result, "suggested_weight", None)),
            self._serialize_list(getattr(result, "correlation_flags", None)),
            self._serialize_list(getattr(result, "structural_exit", None)),
            self._serialize_optional(getattr(result, "quant_exit_target", None)),
            getattr(result, "risk_adjusted_action", None) or "",
            self._serialize_optional(getattr(result, "risk_contribution", None)),
        ]

    @staticmethod
    def _parse_float(value: str | None) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    @staticmethod
    def _parse_optional_bool(value: str | None) -> bool | None:
        if value is None or value == "":
            return None
        return value.strip().lower() in {"true", "1", "yes", "y", "是"}

    @staticmethod
    def _parse_list(value: str | None) -> list[str] | None:
        if value is None or value == "":
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(";") if part.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        if parsed is None:
            return None
        return [str(parsed)]

    def _row_to_result(self, row: list[str] | Mapping[str, str | None]) -> AuditResult:
        """
        将 CSV 行转换为 AuditResult

        Args:
            row: CSV 行数据

        Returns:
            AuditResult: 审计结果对象
        """
        data: Mapping[str, str | None]
        if isinstance(row, Mapping):
            data = row
        else:
            data = dict(zip(self.CSV_COLUMNS, row))

        return AuditResult(
            date=datetime.strptime(data["date"] or "", "%Y-%m-%d"),
            ticker=data["ticker"] or "",
            name=data["name"] or "",
            price=float(data["price"] or "nan"),
            pe_ttm=self._parse_float(data.get("pe_ttm")),
            sentiment_score=int(data["sentiment_score"] or 0),
            sentiment_label=data["sentiment_label"] or "",
            implied_growth=float(data["implied_growth"] or "nan"),
            our_growth=float(data["our_growth"] or "nan"),
            gap=float(data["gap"] or "nan"),
            signal=AuditSignal(data["signal"] or "WAIT"),
            key_narrative=data["key_narrative"] or "",
            key_worry=data["key_worry"] or "",
            key_hope=data["key_hope"] or "",
            # 旧 CSV 没有以下列：用 unknown/None 表示未知，不补看似真实的默认。
            status=data.get("status") or "unknown",
            needs_due_diligence=self._parse_optional_bool(
                data.get("needs_due_diligence")
            ),
            thesis_aligned=True,
            confidence="中",
            reasoning="",
            suggested_weight=self._parse_float(data.get("suggested_weight")),
            correlation_flags=self._parse_list(data.get("correlation_flags")),
            structural_exit=self._parse_list(data.get("structural_exit")),
            quant_exit_target=self._parse_float(data.get("quant_exit_target")),
            risk_adjusted_action=data.get("risk_adjusted_action") or None,
            risk_contribution=self._parse_float(data.get("risk_contribution")),
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
            reader = csv.DictReader(f)
            for row in reader:
                if all(row.get(col) is not None for col in self.CSV_COLUMNS[:14]):
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
