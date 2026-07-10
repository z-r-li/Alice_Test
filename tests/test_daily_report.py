"""daily_report v0.1 测试（100Step 借鉴 PR②，离线、确定性）。

覆盖 handoff 测试清单第 4/5 条：
- tmp 库 fixture → 各分区关键字与数值渲染、NULL→「—」、无 NaN 字样；
- 空库 / 无当日行 → 「本日无决策记录」+ 累计区照常；
- 确定性：同输入两次生成，除页脚「生成时间」行外逐字节相同；
- fail-closed：DB 不存在 / 日期格式错 → 明确抛错，不产空心报表；
- CLI 冒烟（tmp 路径）与 main.py 可选钩子（output.daily_report_html=true）。
"""
from pathlib import Path

import pytest

from src.persistence.sqlite_store import DecisionEntry, OutcomeEntry, SQLiteStore
from src.reporting.daily_report import (
    DEFAULT_OUT_DIR,
    build_daily_report_html,
    main as daily_report_main,
    write_daily_report,
)

ASOF = "2026-07-09"


def _seed_db(db_path: Path) -> None:
    """2–3 行确定性 fixture：1 行满血 BUY（带 coverage）+ 1 行全 NULL WAIT +
    1 行历史决策带 30d 终态兑现（喂累计区）。"""
    with SQLiteStore(str(db_path)) as s:
        s.save_decision(DecisionEntry(
            decision_id=f"601985.SH-{ASOF}", asof_date=ASOF, ticker="601985.SH",
            action="BUY", market="CN", benchmark="沪深300", currency="CNY",
            signal="OPPORTUNITY", signal_semantics="v2", suggested_weight=0.05,
            our_growth=25.0, implied_growth=8.0, gap=17.0,
            falsification="核心政策逆转；毛利率持续下滑",
            pipeline_commit="abc1234",
            cov_links_total=3, cov_links_quant=1,
            cov_links_evidenced=3, cov_links_dd=1,
        ))
        # 非 ok 风格行：预测子与 coverage 按纪律全 NULL（禁止显示为 0 / 编数）
        s.save_decision(DecisionEntry(
            decision_id=f"0700.HK-{ASOF}", asof_date=ASOF, ticker="0700.HK",
            action="WAIT", market="HK", benchmark="HSI",
            signal="WAIT", signal_semantics="v2",
        ))
        # 历史行 + 终态兑现（30d）→ 累计验证区有样本
        s.save_decision(DecisionEntry(
            decision_id="601985.SH-2026-06-20", asof_date="2026-06-20",
            ticker="601985.SH", action="BUY", signal="OPPORTUNITY", gap=12.0,
        ))
        s.record_outcome(OutcomeEntry(
            decision_id="601985.SH-2026-06-20", is_final=1, hit=1,
            excess_return=0.04, horizon_label="30d",
        ))


@pytest.fixture
def seeded_db(tmp_path) -> Path:
    db = tmp_path / "alice.db"
    _seed_db(db)
    return db


class TestBuildDailyReportHtml:
    def test_day_table_renders_values_and_coverage(self, seeded_db):
        html = build_daily_report_html(str(seeded_db), ASOF)
        # 头部
        assert ASOF in html
        assert "当日决策 2 行" in html
        assert "ok 1 行" in html
        assert "v2" in html
        assert "abc1234" in html
        # 当日决策表：数值与 coverage 单元格（evidenced/total·quant n·dd n）
        assert "601985.SH" in html
        assert "OPPORTUNITY" in html
        assert "+17.0" in html
        assert "25.0" in html
        assert "5.0%" in html                      # suggested_weight 0.05
        assert "3/3 · quant 1 · dd 1" in html
        assert "核心政策逆转" in html
        # 尽调队列聚合
        assert "cov_links_dd" in html

    def test_null_renders_dash_never_zero_or_nan(self, seeded_db):
        html = build_daily_report_html(str(seeded_db), ASOF)
        assert "NaN" not in html and "nan" not in html.replace("tabular-nums", "")
        # WAIT 行（单行渲染）：gap/our/implied/仓位/coverage/证伪 六格全「—」
        row = next(l for l in html.splitlines() if "0700.HK" in l)
        assert row.count("—") == 6
        # 绝不把 NULL 显示为 0
        assert ">0<" not in row and ">0.0<" not in row

    def test_cumulative_validation_by_horizon_with_n(self, seeded_db):
        html = build_daily_report_html(str(seeded_db), ASOF)
        assert "累计验证状态" in html
        assert "30d" in html
        assert "100.0%" in html                    # hit_rate = 1/1
        assert "n=1（样本不足）" in html            # n 过小如实标注
        # IC 样本 <2 → store 返回 None → 单元格必须渲染「—」，绝不编成 +0.000
        assert "information_coefficient" in html
        row = next(l for l in html.splitlines() if "全部（每决策最新 final）" in l)
        assert "—" in row
        assert "+0.000" not in html

    def test_dd_queue_lists_ticker(self, seeded_db):
        html = build_daily_report_html(str(seeded_db), ASOF)
        queue_idx = html.index("尽调队列")
        assert "601985.SH" in html[queue_idx:]

    def test_bottom_line_deterministic_template(self, seeded_db):
        html = build_daily_report_html(str(seeded_db), ASOF)
        assert "actionable 1 条" in html
        assert "D-20260709-1" in html              # T0 基线口径台账引用

    def test_no_rows_for_day_but_cumulative_kept(self, seeded_db):
        html = build_daily_report_html(str(seeded_db), "2026-07-10")
        assert "本日无决策记录" in html
        assert "30d" in html                       # 累计区照常
        assert "100.0%" in html

    def test_empty_db(self, tmp_path):
        db = tmp_path / "empty.db"
        SQLiteStore(str(db)).close()               # 只建 schema，零行
        html = build_daily_report_html(str(db), ASOF)
        assert "本日无决策记录" in html
        assert "暂无终态验证样本" in html

    def test_deterministic_except_timestamp(self, seeded_db):
        a = build_daily_report_html(str(seeded_db), ASOF)
        b = build_daily_report_html(str(seeded_db), ASOF)
        strip = lambda s: [l for l in s.splitlines() if "生成时间" not in l]
        assert strip(a) == strip(b)
        # 生成时间戳独占一行（页脚），确保上面的排除口径成立
        assert sum(1 for l in a.splitlines() if "生成时间" in l) == 1

    def test_missing_db_fails_closed(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_daily_report_html(str(tmp_path / "no_such.db"), ASOF)

    def test_bad_date_rejected(self, seeded_db):
        with pytest.raises(ValueError):
            build_daily_report_html(str(seeded_db), "2026/07/09")

    def test_html_escapes_content(self, tmp_path):
        db = tmp_path / "esc.db"
        with SQLiteStore(str(db)) as s:
            s.save_decision(DecisionEntry(
                decision_id=f"AAPL-{ASOF}", asof_date=ASOF, ticker="AAPL",
                action="WAIT", falsification="<script>alert(1)</script>",
            ))
        html = build_daily_report_html(str(db), ASOF)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_self_contained_no_external_refs_no_js(self, seeded_db):
        html = build_daily_report_html(str(seeded_db), ASOF)
        assert "<script" not in html
        assert "http://" not in html and "https://" not in html
        assert "@import" not in html and "url(" not in html


class TestWriteAndCli:
    def test_write_daily_report_path_and_content(self, seeded_db, tmp_path):
        out = write_daily_report(str(seeded_db), ASOF, tmp_path / "reports")
        assert out == tmp_path / "reports" / f"daily_{ASOF}.html"
        text = out.read_text(encoding="utf-8")
        assert "601985.SH" in text

    def test_cli_smoke(self, seeded_db, tmp_path, capsys):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "persistence:\n"
            "  backend: \"sqlite\"\n"
            f"  sqlite_path: \"{str(seeded_db).replace(chr(92), '/')}\"\n"
            "targets:\n"
            "  - ticker: \"601985.SH\"\n"
            "    name: \"中国核电\"\n"
            "    thesis: \"测试信念\"\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "out"
        rc = daily_report_main([
            "--config", str(cfg), "--date", ASOF, "--out", str(out_dir),
        ])
        assert rc == 0
        report = out_dir / f"daily_{ASOF}.html"
        assert report.exists()
        assert "601985.SH" in report.read_text(encoding="utf-8")
        assert str(report) in capsys.readouterr().out

    def test_main_hook_generates_report_when_enabled(self, monkeypatch, tmp_path):
        # output.daily_report_html=true → run() 末尾生成日报（默认关不生成，见下一测试）
        from tests.test_decision_log_store import _make_sqlite_pipeline

        pipeline, config, _db_path = _make_sqlite_pipeline(monkeypatch, tmp_path)
        config.output.daily_report_html = True
        out_dir = tmp_path / "daily_report"
        monkeypatch.setattr(
            "src.reporting.daily_report.DEFAULT_OUT_DIR", str(out_dir)
        )
        results = pipeline.run()
        asof = results[0].date.strftime("%Y-%m-%d")
        report = out_dir / f"daily_{asof}.html"
        assert report.exists()
        text = report.read_text(encoding="utf-8")
        assert "601985.SH" in text
        assert "3/3 · quant 1 · dd 1" in text     # coverage 端到端进日报

    def test_main_hook_off_by_default(self, monkeypatch, tmp_path):
        from tests.test_decision_log_store import _make_sqlite_pipeline

        pipeline, config, _db_path = _make_sqlite_pipeline(monkeypatch, tmp_path)
        assert config.output.daily_report_html is False
        out_dir = tmp_path / "daily_report"
        monkeypatch.setattr(
            "src.reporting.daily_report.DEFAULT_OUT_DIR", str(out_dir)
        )
        pipeline.run()
        assert not out_dir.exists()               # 默认关：零副作用


class TestValidationSampleCaliber:
    """n 样本量与 store 指标同口径的鉴别力测试（复审补强）：
    去重轴 = MAX(outcome_id) 最新 final、hit 剔 WAIT（AVOID 计入）、IC 不剔 WAIT。
    fixture 特意构造 re-score 与 WAIT 带 final，任一口径漂移断言必炸。"""

    def test_n_dedups_rescored_final_and_wait_scope(self, tmp_path):
        db = tmp_path / "caliber.db"
        with SQLiteStore(str(db)) as s:
            # b-1：re-score 两条 is_final=1（hit 0→1）——n 只计 1（不去重则 2）
            s.save_decision(DecisionEntry(decision_id="b-1", asof_date="2026-06-01",
                                          ticker="B", action="BUY", gap=5.0))
            s.record_outcome(OutcomeEntry(decision_id="b-1", is_final=1, hit=0,
                                          excess_return=-0.01))
            s.record_outcome(OutcomeEntry(decision_id="b-1", is_final=1, hit=1,
                                          excess_return=0.03))
            # w-1：WAIT 带 final——剔出 hit 样本（actionable 口径），但 gap 非空进 IC
            s.save_decision(DecisionEntry(decision_id="w-1", asof_date="2026-06-01",
                                          ticker="W", action="WAIT", gap=1.0))
            s.record_outcome(OutcomeEntry(decision_id="w-1", is_final=1, hit=0,
                                          excess_return=0.02))
        html = build_daily_report_html(str(db), ASOF)
        # hit：仅 b-1 的最新 final（hit=1）→ 100.0%、n=1（不去重→n=2；WAIT 计入→n=2）
        assert "100.0%" in html
        assert "n=1（样本不足）" in html
        # IC：b-1(5.0, +0.03) 与 w-1(1.0, +0.02) 两点正序对齐 → +1.000、n=2
        assert "n=2（样本不足）" in html
        assert "+1.000" in html

    def test_non_padded_date_normalized(self, seeded_db, tmp_path):
        # '2026-7-9' 须归一为 '2026-07-09'：当日行可见（不误报「本日无决策记录」），
        # 文件名同样补零——否则 CLI 手输日期会静默产出空心报表。
        html = build_daily_report_html(str(seeded_db), "2026-7-9")
        assert "601985.SH" in html
        assert "本日无决策记录" not in html
        out = write_daily_report(str(seeded_db), "2026-7-9", tmp_path / "norm")
        assert out.name == "daily_2026-07-09.html"
