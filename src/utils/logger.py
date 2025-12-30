"""
日志工具

职责：
- 统一日志格式
- 记录运行统计信息（成功/失败数、Token 消耗等）
- 支持 DEBUG 模式（通过 ALICE_DEBUG 环境变量或 --debug 参数）
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def is_debug_mode() -> bool:
    """
    检查是否启用 DEBUG 模式

    可通过设置环境变量 ALICE_DEBUG=1 启用

    Returns:
        bool: 是否为 DEBUG 模式
    """
    return os.environ.get("ALICE_DEBUG", "").lower() in ("1", "true", "yes")


@dataclass
class RunStatistics:
    """单次运行统计信息"""
    run_date: datetime
    total_targets: int = 0
    success_count: int = 0
    data_error_count: int = 0
    llm_error_count: int = 0
    total_llm_calls: int = 0
    total_tokens_used: int = 0
    avg_llm_latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


def setup_logger(
    name: str = "alice_test",
    level: int | None = None,
    log_file: str | Path | None = None,
) -> logging.Logger:
    """
    配置日志器

    Args:
        name: 日志器名称
        level: 日志级别，默认 INFO，若 ALICE_DEBUG=1 则自动使用 DEBUG
        log_file: 日志文件路径（可选）

    Returns:
        logging.Logger: 配置好的日志器
    """
    # 自动检测 DEBUG 模式
    if level is None:
        level = logging.DEBUG if is_debug_mode() else logging.INFO

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    # 格式化器（DEBUG 模式下显示更多信息）
    if level == logging.DEBUG:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器（可选）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "alice_test") -> logging.Logger:
    """
    获取日志器实例

    Args:
        name: 日志器名称

    Returns:
        logging.Logger: 日志器实例
    """
    return logging.getLogger(name)


class AuditLogger:
    """审计专用日志器，带运行统计功能"""

    def __init__(self, logger: logging.Logger | None = None):
        """
        初始化审计日志器

        Args:
            logger: 底层日志器，默认使用 alice_test
        """
        self._logger = logger or get_logger("alice_test")
        self._current_stats: RunStatistics | None = None

    def start_run(self, total_targets: int) -> None:
        """
        开始一次审计运行

        Args:
            total_targets: 本次运行的标的总数
        """
        self._current_stats = RunStatistics(
            run_date=datetime.now(),
            total_targets=total_targets,
        )
        self._logger.info(f"Starting audit run for {total_targets} targets")

    def log_success(self, ticker: str) -> None:
        """记录成功"""
        if self._current_stats:
            self._current_stats.success_count += 1
        self._logger.info(f"[{ticker}] Audit completed successfully")

    def log_data_error(self, ticker: str, error: str) -> None:
        """记录数据错误"""
        if self._current_stats:
            self._current_stats.data_error_count += 1
            self._current_stats.errors.append(f"[{ticker}] Data error: {error}")
        self._logger.warning(f"[{ticker}] Data error: {error}")

    def log_llm_error(self, ticker: str, error: str) -> None:
        """记录 LLM 错误"""
        if self._current_stats:
            self._current_stats.llm_error_count += 1
            self._current_stats.errors.append(f"[{ticker}] LLM error: {error}")
        self._logger.error(f"[{ticker}] LLM error: {error}")

    def log_debug(self, message: str) -> None:
        """记录调试信息（仅在 DEBUG 模式下输出）"""
        self._logger.debug(message)

    def log_llm_call(self, tokens_used: int, latency_ms: float) -> None:
        """记录 LLM 调用统计"""
        if self._current_stats:
            self._current_stats.total_llm_calls += 1
            self._current_stats.total_tokens_used += tokens_used
            # 更新平均延迟
            n = self._current_stats.total_llm_calls
            prev_avg = self._current_stats.avg_llm_latency_ms
            self._current_stats.avg_llm_latency_ms = prev_avg + (latency_ms - prev_avg) / n

    def end_run(self) -> RunStatistics | None:
        """
        结束运行并返回统计信息

        Returns:
            RunStatistics | None: 运行统计
        """
        if self._current_stats:
            stats = self._current_stats
            self._logger.info(
                f"Run completed: {stats.success_count}/{stats.total_targets} success, "
                f"{stats.data_error_count} data errors, {stats.llm_error_count} LLM errors, "
                f"{stats.total_llm_calls} LLM calls, {stats.total_tokens_used} tokens used"
            )
            self._current_stats = None
            return stats
        return None
