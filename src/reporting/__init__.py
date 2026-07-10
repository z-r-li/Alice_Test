"""报告生成（只读、零 LLM）：目前仅 daily_report（100Step 借鉴 PR②）。

不在包 __init__ 里 eager import 子模块：`python -m src.reporting.daily_report`
会先 import 本包再以 runpy 执行同名子模块，eager import 会让每次 CLI 调用都报
`RuntimeWarning: 'src.reporting.daily_report' found in sys.modules`。
用方直接 `from src.reporting.daily_report import build_daily_report_html`。
"""
