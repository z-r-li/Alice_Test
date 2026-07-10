"""报告生成（只读、零 LLM）：目前仅 daily_report（100Step 借鉴 PR②）。"""
from .daily_report import build_daily_report_html, write_daily_report

__all__ = ["build_daily_report_html", "write_daily_report"]
