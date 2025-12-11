"""
持久化抽象基类
"""
from abc import ABC, abstractmethod
from datetime import datetime

from ..engines.gap_calculator import AuditResult


class AuditReportStore(ABC):
    """审计报告存储抽象基类"""

    @abstractmethod
    def save(self, result: AuditResult) -> None:
        """
        保存单条审计结果

        Args:
            result: 审计结果
        """
        ...

    @abstractmethod
    def save_batch(self, results: list[AuditResult]) -> None:
        """
        批量保存审计结果

        Args:
            results: 审计结果列表
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def get_by_date(self, date: datetime) -> list[AuditResult]:
        """
        按日期查询所有标的审计结果

        Args:
            date: 审计日期

        Returns:
            list[AuditResult]: 该日所有审计结果
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def get_latest(self, ticker: str) -> AuditResult | None:
        """
        获取指定标的最新审计结果

        Args:
            ticker: 证券代码

        Returns:
            AuditResult | None: 最新结果或 None
        """
        ...
