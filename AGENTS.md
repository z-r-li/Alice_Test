# AGENTS.md · Alice Test

本文件给所有 agent（Claude Code、Codex、Cowork）共用的工程约定。项目上下文、必读文档清单和当前阶段在本地专属的 `CLAUDE.md`（gitignored，不入库）。

## 代码约定

- **SQLite 只读路径**：报表 / 分析等纯读一律 `SQLiteStore(readonly=True)`（`mode=ro` URI、零 DDL；schema 不全就 fail-closed，提示先用可写连接开一次完成迁移），不要裸开 `SQLiteStore`。WAL 库用 `mode=ro` 打开仍会生成 `-wal/-shm` → 仓内做法是读文件头拒绝 WAL，并提示 `PRAGMA journal_mode=DELETE`。
- `output.format` 不被 CLI 消费：`main.py` 无条件用 `CSVReportWriter`，`SQLiteReportStore` 未接线；`persistence.backend=sqlite` 只落 S7 决策日志。写文档时别把“类存在”写成“能力已接通”，从 docstring 抄进文档前先核实实现。
- DeepSeek/openai SDK：`reasoning_effort` 必须放进 `extra_body`（SDK 下限版本的 `create()` 不收这个顶层 kwarg），勿改回顶层。

## 审查

- 仓库无 CI，Codex 以 inline 评论给 P2。处理 = push 修复 → `gh api -X POST repos/{repo}/pulls/{pr}/comments/{comment_id}/replies -f body=...` 逐条回复 → GraphQL `resolveReviewThread(threadId)`（先查 `reviewThreads` 把 comment databaseId 映射到 thread node id）。评论 `@codex review` 触发复审；Codex 结果不确定（同一 commit 可能一次 3 条、一次 0 条）。

## 专用机（`xiaodao-box`）

- box 解析不了 github.com，不能直接 `git pull` / `fetch` → 用增量 bundle：本地 `git bundle create <file> <box_head>..origin/main` → `scp` → box 上 `git bundle verify` + fetch 进 `refs/remotes/origin/main` + `git merge --ff-only`。box 上不 commit、不 push、不切分支。
- box 的 `config.yaml` 只在 box 上（gitignored，已部署）；`main.py` 默认读 cwd 下的 `config.yaml`。
- box DNS 会间歇抖动（`getaddrinfo 11001`），Windows 负缓存会把一次抖动放大成整轮失败 → 源探测失败先复测，别直接判源不可达。各源可达性见 `src/data_ingestion/text/a_share/coordinator.py` 的 `SOURCE_REACHABILITY`；`skip_unreachable_sources` 保持 `true`（CDX-6，2026-07-08）。
