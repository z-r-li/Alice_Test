"""
_print_summary 在非 UTF-8 控制台下的健壮性测试。

回归场景（2026-06-17 P1 复验 §六 发现）：Windows GBK/cp936 控制台下，审计完成、
CSV 落盘之后，摘要打印里的 '✓'(U+2713)/'✗' 会触发 UnicodeEncodeError，异常上抛后
污染进程退出码，使每日 cron 把成功的运行误报为失败。

这里把 sys.stdout 换成 encoding='gbk'、errors='strict' 的真实 TextIO 流，验证：
  1. 该流直接写 '✓' 确实会炸（确认前置条件成立）；
  2. _print_summary 在此流下不抛错（兜底 errors='replace'）；
  3. _safe_print 的兜底逻辑可用；
  4. _reconfigure_stdio 调用安全（含被替换为 gbk 流的情况）。
"""
import io
import sys
from datetime import datetime

import pytest

from src.engines.gap_calculator import AuditResult, AuditSignal
from src.main import AliceTestPipeline, _reconfigure_stdio, _safe_print


def _make_result(status: str = "ok") -> AuditResult:
    return AuditResult(
        date=datetime(2026, 6, 17),
        ticker="0700.HK",
        name="腾讯控股",
        price=380.0,
        pe_ttm=18.0,
        sentiment_score=55,
        sentiment_label="中性",
        implied_growth=8.0,
        key_narrative="市场预期平稳增长",
        key_worry="监管不确定性",
        key_hope="游戏与广告复苏",
        thesis_aligned=True,
        our_growth=18.0,
        confidence="高",
        reasoning="基本面支撑",
        gap=10.0,
        signal=AuditSignal.OPPORTUNITY,
        status=status,
    )


def _gbk_stdout() -> io.TextIOWrapper:
    """模拟 Windows zh-CN 默认控制台：GBK 编码、严格错误处理。"""
    return io.TextIOWrapper(
        io.BytesIO(), encoding="gbk", errors="strict", newline="", write_through=True
    )


def test_gbk_stream_rejects_check_mark():
    """前置条件：'✓' 在 GBK 严格流下确实无法编码（否则本测试没有意义）。"""
    stream = _gbk_stdout()
    with pytest.raises(UnicodeEncodeError):
        stream.write("✓")
        stream.flush()


def test_print_summary_does_not_raise_under_gbk_stdout(monkeypatch):
    """核心回归：GBK 控制台下打印含 '✓'/'✗' 的摘要不应抛错。"""
    monkeypatch.setattr(sys, "stdout", _gbk_stdout())

    # _print_summary 不使用任何实例属性，用 __new__ 绕过重型 __init__
    pipeline = AliceTestPipeline.__new__(AliceTestPipeline)
    results = [_make_result(status="ok"), _make_result(status="data_error")]

    # 不抛 UnicodeEncodeError 即为通过
    pipeline._print_summary(results, success_count=1, error_count=1)

    # 摘要内容确实被写出（'✓' 退化为替代符，中文与代码保留）
    sys.stdout.flush()
    written = sys.stdout.buffer.getvalue().decode("gbk", errors="replace")
    assert "审计摘要" in written
    assert "0700.HK" in written


def test_print_summary_empty_results_under_gbk(monkeypatch):
    """空结果集也不应在 GBK 流下抛错。"""
    monkeypatch.setattr(sys, "stdout", _gbk_stdout())
    pipeline = AliceTestPipeline.__new__(AliceTestPipeline)
    pipeline._print_summary([], success_count=0, error_count=0)


def test_safe_print_falls_back_on_unencodable(monkeypatch):
    """_safe_print 直接面对 GBK 流时，'✓' 不抛错并落地为替代符。"""
    monkeypatch.setattr(sys, "stdout", _gbk_stdout())
    _safe_print("结果 ✓ done")
    sys.stdout.flush()
    written = sys.stdout.buffer.getvalue().decode("gbk", errors="replace")
    assert "结果" in written
    assert "done" in written


def test_reconfigure_stdio_is_safe(monkeypatch):
    """_reconfigure_stdio 在普通/无 reconfigure 的流上都不应抛错。"""
    # 普通情况（pytest 捕获的流可能支持也可能不支持 reconfigure）：不抛即可
    _reconfigure_stdio()

    # 无 reconfigure 方法的流（如 BytesIO 之类替身）：应被安全跳过
    class _NoReconfigure(io.StringIO):
        pass

    monkeypatch.setattr(sys, "stdout", _NoReconfigure())
    monkeypatch.setattr(sys, "stderr", _NoReconfigure())
    _reconfigure_stdio()  # 不抛 AttributeError
