"""
自包含 HTML 日报（100Step 借鉴 PR②，daily_report v0.1）。

从决策日志 SQLite **只读**生成单文件日报：当日决策表（含 coverage 四计数）+ 累计
hit_rate / information_coefficient（复用 ``SQLiteStore`` 既有口径与去重轴，#81）+
尽调队列 + 确定性 Bottom line。**零 LLM 调用、零网络**；同输入同字节——唯一的
非确定性是页脚「生成时间」单行（测试断言时排除该行）。

真只读（PR #90 复审落地）：以 ``SQLiteStore(db_path, readonly=True)``（SQLite
``mode=ro`` URI）打开，**零 DDL / 零写 / 零边车**——指向生产库不会动 schema，指向
只读快照 / 只读文件系统亦可用。两类异常库 fail-closed 不静默：旧库缺迁移列 →
开库即抛明确指引（先用可写连接打开一次完成自动迁移）；WAL 模式库 → 拒绝并指引
切回 delete 模式（``mode=ro`` 对 WAL 仍会落 -wal/-shm 边车，破坏上述承诺）。

自包含约定：单文件 HTML、内嵌 CSS、UTF-8、无 JS、无外链 / 无外部字体——浏览器
直开与 Lark 粘贴均可。fail-closed 风格：NULL 显示「—」、绝不显示为 0 或编数；
无当日行 / 空库如实输出「本日无决策记录」，累计区照常。

用法（box cron 推荐在 daily-run 后链式调用）：
    python -m src.reporting.daily_report --config config.yaml [--date YYYY-MM-DD] [--out DIR]
"""
from __future__ import annotations

import argparse
import html as _html
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..persistence.sqlite_store import SQLiteStore

REPORT_VERSION = "daily_report v0.1"
DEFAULT_OUT_DIR = "./output/daily_report"
# 累计验证区样本量小于该值时如实加标「样本不足」（只加标签，不隐藏数值）
MIN_SAMPLE_N = 5

_NULL = "—"  # NULL 的展示占位：语义是「未知/没走到那」，禁止显示为 0 或编数

_STYLE = """
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       margin: 24px auto; max-width: 960px; color: #1a1a1a; line-height: 1.5; }
h1 { font-size: 20px; border-bottom: 2px solid #1a1a1a; padding-bottom: 8px; }
h2 { font-size: 16px; margin-top: 28px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
th { background: #f0f0f0; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
p.meta { font-size: 13px; color: #444; }
p.empty { color: #666; font-style: italic; }
p.bottomline { font-size: 14px; background: #f6f6f6; padding: 10px 12px;
               border-left: 3px solid #888; }
p.footer { font-size: 11px; color: #999; margin-top: 32px;
           border-top: 1px solid #ddd; padding-top: 8px; }
"""


# ---- 格式化（fail-closed：None → 「—」，绝不补 0） ---------------------------

def _esc(v: Any) -> str:
    return _html.escape(str(v))


def _fmt_num(v: Optional[float], pattern: str = "{:.1f}") -> str:
    return _NULL if v is None else pattern.format(v)


def _fmt_signed(v: Optional[float]) -> str:
    return _NULL if v is None else f"{v:+.1f}"


def _fmt_weight(v: Optional[float]) -> str:
    return _NULL if v is None else f"{v * 100:.1f}%"


def _fmt_int(v: Optional[int]) -> str:
    return _NULL if v is None else str(v)


def _fmt_coverage(row: dict) -> str:
    """coverage 单元格：``evidenced/total · quant n · dd n``；total 为 NULL（没走到
    证据链）→ 整格「—」。四列同批写入，个别列缺失按「—」如实显示、不补 0。"""
    total = row.get("cov_links_total")
    if total is None:
        return _NULL
    return (
        f"{_fmt_int(row.get('cov_links_evidenced'))}/{total}"
        f" · quant {_fmt_int(row.get('cov_links_quant'))}"
        f" · dd {_fmt_int(row.get('cov_links_dd'))}"
    )


def _truncate(s: Optional[str], limit: int = 80) -> str:
    if not s or not str(s).strip():
        return _NULL
    s = str(s).strip()
    return s if len(s) <= limit else s[:limit] + "…"


# ---- 累计验证区的样本量（与 store 指标同口径，仅计数） -----------------------

def _validation_sample_counts(
    conn: sqlite3.Connection, horizon: Optional[str]
) -> tuple[int, int]:
    """(n_hit, n_ic)：与 ``SQLiteStore.hit_rate`` / ``information_coefficient`` 同口径
    的样本量（store 方法只返回指标不返回 n，此处只补计数、不复算指标）。

    同一去重轴：每 decision 取 ``MAX(outcome_id)`` 的最新 final（``horizon`` 给定时
    仅在该档位内取最新）；hit 样本 = 最新 final 的 ``hit`` 非 NULL 且 action ≠ WAIT
    （actionable 口径，AVOID 计入，D-20260705-1）；IC 样本 = 最新 final 的
    ``excess_return`` 非 NULL 且预测子 ``gap`` 非 NULL。
    """
    hz_outer = " AND o.horizon_label = ?" if horizon else ""
    hz_sub = " AND o2.horizon_label = ?" if horizon else ""
    base = (
        "FROM decision_log d JOIN decision_outcome o "
        "ON o.decision_id = d.decision_id "
        "WHERE o.is_final = 1" + hz_outer +
        " AND o.outcome_id = ("
        "  SELECT MAX(o2.outcome_id) FROM decision_outcome o2 "
        "  WHERE o2.decision_id = d.decision_id AND o2.is_final = 1" + hz_sub + ")"
    )
    params: list[Any] = [horizon, horizon] if horizon else []
    n_hit = conn.execute(
        "SELECT COUNT(*) " + base + " AND o.hit IS NOT NULL AND d.action != 'WAIT'",
        params,
    ).fetchone()[0]
    n_ic = conn.execute(
        "SELECT COUNT(*) " + base
        + " AND o.excess_return IS NOT NULL AND d.gap IS NOT NULL",
        params,
    ).fetchone()[0]
    return int(n_hit), int(n_ic)


def _n_label(n: int) -> str:
    """样本量展示：n 过小如实标「样本不足」（不隐藏 n 本身）。"""
    if n < MIN_SAMPLE_N:
        return f"n={n}（样本不足）"
    return f"n={n}"


def _normalize_date(asof_date: str) -> str:
    """校验并归一 YYYY-MM-DD（补零）。strptime 接受 '2026-7-9' 这类未补零输入，
    若不归一直接拿去精确匹配 asof_date 列，会静默查空、误报「本日无决策记录」。"""
    try:
        return datetime.strptime(asof_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"asof_date 必须为 YYYY-MM-DD：{asof_date!r}") from e


# ---- 各分区渲染 --------------------------------------------------------------

def _render_header(asof_date: str, day_rows: list[dict]) -> str:
    n_day = len(day_rows)
    # ok 行口径 = 预测子（gap）非空行：非 ok 行按既有纪律预测子一律置 NULL
    # （_build_decision_entry），故 gap 非空 ≙ status=ok 的可用预测行。
    n_ok = sum(1 for r in day_rows if r.get("gap") is not None)
    semantics = sorted({r.get("signal_semantics") or _NULL for r in day_rows}) or [_NULL]
    commits = sorted({r["pipeline_commit"] for r in day_rows if r.get("pipeline_commit")})
    commits_str = "、".join(commits) if commits else _NULL
    return (
        f"<p class=\"meta\">日期：{_esc(asof_date)} ｜ 当日决策 {n_day} 行"
        f"（ok {n_ok} 行，口径：预测子 gap 非空） ｜ "
        f"signal_semantics：{_esc('、'.join(semantics))} ｜ "
        f"pipeline_commit：{_esc(commits_str)}</p>\n"
    )


def _render_day_table(day_rows: list[dict]) -> str:
    if not day_rows:
        return "<p class=\"empty\">本日无决策记录</p>\n"
    head = (
        "<tr><th>ticker</th><th>signal</th><th>action</th><th>gap</th>"
        "<th>our_growth</th><th>implied_growth</th><th>建议仓位</th>"
        "<th>coverage</th><th>证伪条件（摘要）</th></tr>"
    )
    body = []
    for r in day_rows:
        body.append(
            "<tr>"
            f"<td>{_esc(r['ticker'])}</td>"
            f"<td>{_esc(r.get('signal') or _NULL)}</td>"
            f"<td>{_esc(r['action'])}</td>"
            f"<td class=\"num\">{_esc(_fmt_signed(r.get('gap')))}</td>"
            f"<td class=\"num\">{_esc(_fmt_num(r.get('our_growth')))}</td>"
            f"<td class=\"num\">{_esc(_fmt_num(r.get('implied_growth')))}</td>"
            f"<td class=\"num\">{_esc(_fmt_weight(r.get('suggested_weight')))}</td>"
            f"<td>{_esc(_fmt_coverage(r))}</td>"
            f"<td>{_esc(_truncate(r.get('falsification')))}</td>"
            "</tr>"
        )
    return "<table>\n" + head + "\n" + "\n".join(body) + "\n</table>\n"


def _render_validation(store: SQLiteStore) -> str:
    """累计验证状态：hit_rate / IC 复用 store 既有方法（含 horizon 与 actionable
    口径，#81），按 horizon_label 分行 + 跨 horizon 默认口径一行，必须带样本量 n。"""
    # 空串 horizon_label 一并排除：store.hit_rate(horizon="") 因 falsy 会退化成
    # 跨 horizon 默认口径，渲染出一行空白标签的重复聚合，误导读者。
    horizons = [
        r["horizon_label"]
        for r in store.conn.execute(
            "SELECT DISTINCT horizon_label FROM decision_outcome "
            "WHERE is_final = 1 AND horizon_label IS NOT NULL AND horizon_label != '' "
            "ORDER BY horizon_label"
        )
    ]
    n_final = store.conn.execute(
        "SELECT COUNT(*) FROM decision_outcome WHERE is_final = 1"
    ).fetchone()[0]
    if n_final == 0:
        return "<p class=\"empty\">暂无终态验证样本（尚无 is_final=1 的兑现记录）</p>\n"

    head = (
        "<tr><th>horizon</th><th>hit_rate</th><th>样本</th>"
        "<th>information_coefficient (gap)</th><th>样本</th></tr>"
    )
    rows: list[tuple[str, Optional[str]]] = [("全部（每决策最新 final）", None)]
    rows += [(hl, hl) for hl in horizons]
    body = []
    for label, hz in rows:
        hr = store.hit_rate(horizon=hz)
        ic = store.information_coefficient("gap", horizon=hz)
        n_hit, n_ic = _validation_sample_counts(store.conn, hz)
        hr_s = _NULL if hr is None else f"{hr * 100:.1f}%"
        ic_s = _NULL if ic is None else f"{ic:+.3f}"
        body.append(
            "<tr>"
            f"<td>{_esc(label)}</td>"
            f"<td class=\"num\">{_esc(hr_s)}</td>"
            f"<td>{_esc(_n_label(n_hit))}</td>"
            f"<td class=\"num\">{_esc(ic_s)}</td>"
            f"<td>{_esc(_n_label(n_ic))}</td>"
            "</tr>"
        )
    return "<table>\n" + head + "\n" + "\n".join(body) + "\n</table>\n"


def _render_dd_queue(day_rows: list[dict]) -> str:
    dd_rows = [
        r for r in day_rows
        if r.get("cov_links_dd") is not None and r["cov_links_dd"] > 0
    ]
    if not dd_rows:
        return "<p class=\"empty\">本日无待人工尽调环节（或当日行未走到证据链）</p>\n"
    head = "<tr><th>ticker</th><th>尽调环节数 (cov_links_dd)</th></tr>"
    body = [
        f"<tr><td>{_esc(r['ticker'])}</td>"
        f"<td class=\"num\">{_esc(r['cov_links_dd'])}</td></tr>"
        for r in dd_rows
    ]
    return "<table>\n" + head + "\n" + "\n".join(body) + "\n</table>\n"


def _render_bottom_line(day_rows: list[dict], store: SQLiteStore) -> str:
    """Bottom line：确定性模板句，不做 LLM 生成。"""
    n_day = len(day_rows)
    n_ok = sum(1 for r in day_rows if r.get("gap") is not None)
    # actionable 口径（D-20260705-1）：只剔 WAIT，AVOID 计入
    n_act = sum(1 for r in day_rows if r["action"] != "WAIT")
    n_hit, n_ic = _validation_sample_counts(store.conn, None)
    return (
        "<p class=\"bottomline\">今日决策 "
        f"{n_day} 条（ok {n_ok}），actionable {n_act} 条（口径：action ≠ WAIT，"
        f"AVOID 计入）；累计终态验证样本 hit n={n_hit} / IC n={n_ic}"
        "（跨 horizon 最新 final 口径）。注：T0 前 shakedown 行未在本表剔除，"
        "基线口径见台账 D-20260709-1。</p>\n"
    )


# ---- 主入口 ------------------------------------------------------------------

def build_daily_report_html(db_path: str, asof_date: str) -> str:
    """由决策日志 SQLite 生成自包含 HTML 日报（只读、零 LLM、确定性）。

    Args:
        db_path: 决策日志 SQLite 文件路径（``config.persistence.sqlite_path`` 同源）。
        asof_date: 报告日 YYYY-MM-DD（按 ``decision_log.asof_date`` 精确匹配当日行）。

    Raises:
        ValueError: asof_date 非 YYYY-MM-DD（或 db_path 为 ``:memory:``——只读打开
            全新内存库无意义，store 直接拒绝）。
        FileNotFoundError: DB 文件不存在（fail-closed：不静默建空库、不产出空心报表）。
        RuntimeError: 库 schema 落后于当前版本（旧库缺迁移列，按报错指引先用可写
            连接打开一次完成自动迁移），或库为 WAL 模式（``mode=ro`` 仍会落
            -wal/-shm 边车，按指引 ``PRAGMA journal_mode=DELETE`` 切回后再生成）。
    """
    asof_date = _normalize_date(asof_date)
    if db_path != ":memory:" and not Path(db_path).exists():
        raise FileNotFoundError(f"决策日志 DB 不存在: {db_path}")

    # 真只读打开（mode=ro，PR #90 复审）：零 DDL / 零写——不迁移 schema、不落
    # journal；旧库缺迁移列由 store 开库门禁抛明确指引（fail-closed，不静默）。
    with SQLiteStore(db_path, readonly=True) as store:
        day_rows = store.get_decisions(since=asof_date, until=asof_date)
        parts = [
            "<!DOCTYPE html>",
            "<html lang=\"zh-CN\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            f"<title>小道决策日报 {_esc(asof_date)}</title>",
            f"<style>{_STYLE}</style>",
            "</head>",
            "<body>",
            f"<h1>小道决策日报 · {_esc(asof_date)}</h1>",
            _render_header(asof_date, day_rows),
            "<h2>一、当日决策表</h2>",
            _render_day_table(day_rows),
            "<h2>二、累计验证状态</h2>",
            _render_validation(store),
            "<h2>三、尽调队列（当日）</h2>",
            _render_dd_queue(day_rows),
            "<h2>四、Bottom line</h2>",
            _render_bottom_line(day_rows, store),
            # 页脚：生成时间是全文件唯一的非确定性内容，独占一行（测试断言时排除）
            (
                f"<p class=\"footer\">生成时间 "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                f" ｜ {REPORT_VERSION} ｜ db: {_esc(db_path)}</p>"
            ),
            "</body>",
            "</html>",
        ]
    return "\n".join(parts) + "\n"


def write_daily_report(
    db_path: str, asof_date: str, out_dir: str | Path = DEFAULT_OUT_DIR
) -> Path:
    """生成日报并写盘，返回输出路径（``out_dir/daily_YYYY-MM-DD.html``）。"""
    asof_date = _normalize_date(asof_date)   # 文件名与报表内容用同一归一化日期
    text = build_daily_report_html(db_path, asof_date)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"daily_{asof_date}.html"
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    """CLI：``python -m src.reporting.daily_report --config config.yaml
    [--date YYYY-MM-DD] [--out DIR]``。db 路径取 ``config.persistence.sqlite_path``
    （与 main._write_decision_log 同源）。"""
    parser = argparse.ArgumentParser(
        description="从决策日志 SQLite 生成自包含 HTML 日报（只读、零 LLM）"
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml",
        help="配置文件路径（默认 config.yaml；取 persistence.sqlite_path）",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="报告日 YYYY-MM-DD（默认今天）",
    )
    parser.add_argument(
        "--out", type=str, default=DEFAULT_OUT_DIR,
        help=f"输出目录（默认 {DEFAULT_OUT_DIR}）",
    )
    args = parser.parse_args(argv)

    from ..config import ConfigManager

    config = ConfigManager(args.config).load()
    asof = args.date or datetime.now().strftime("%Y-%m-%d")
    path = write_daily_report(config.persistence.sqlite_path, asof, args.out)
    # 只打 ASCII 安全内容（路径），避免 Windows GBK 控制台编码炸退出码
    print(str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
