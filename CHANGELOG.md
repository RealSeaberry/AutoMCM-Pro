# Changelog

All notable changes to AutoMCM-Pro are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Version scheme: [Semantic Versioning](https://semver.org/).

---

## [0.3.0] — 2026-08-25

### Added

#### Los Alamos Exploration Layer (optional, auto-triggered addon)
- Hypothesis tree/DAG materialized view (`scripts/los_alamos/hypothesis_tree.py`),
  event-sourced from an append-only message bus (`bus.py`); four evaluation
  tracks: Track 0 (semantic screening), Track R "Bletchley" (red-team stress
  test), Track 1 (entropy-weight + TOPSIS objective ranking), Track 2
  (qualitative pairwise judge panel, Copeland ranking, Shannon-entropy
  disagreement)
- Six autonomous trigger criteria (`SKILL.md` path C Step 0), including a new
  "problem-complexity initial judgment" checkable as early as
  `problem_analysis` — no longer requires an explicit human request or
  literature-survey-stage evidence to fire
- New `LOS_ALAMOS_METHOD_CATALOG.md` — six-category MCM paradigm taxonomy
  (optimization / prediction / evaluation / simulation / classification /
  network) used by Alsos literature surveys and Director's first-layer branch
  selection to widen candidate coverage beyond ad-hoc search
- Elastic branch width (2 branches under time pressure, 3–4 when time budget
  allows) and deeper branching support (same-paradigm technical-choice
  sub-branches, `depth` + `--parent-ids`)
- Governance rule (SOP §9.2.6): branch decisions must query
  `hypothesis_tree.py status` before acting, not rely on narrative memory —
  wired into `SKILL.md` at Step 5 (build/verify dispatch) and Step 9 (finals)
- Fixed: `adjudicate.py screen`/`redteam` previously left the
  `hypothesis_tree_{N}.json` materialized-view snapshot stale until the next
  `hypothesis_tree.py` invocation; both now call `_sync_tree()` immediately

#### RAND Delphi — Track 2 anonymous multi-round convergence
- `adjudicate.py panel-vote --round` / `panel-entropy --round` /
  `delphi-summary`; capped at 2 retry rounds (SOP §9.6)

#### Project Skunk Works — lightweight mode
- `pipeline_manager.py init --skunk-works`, relaxes citation gate (≥1 vs ≥2)
  and Checkpoint report verbosity; §4 self-verification mandate is explicitly
  **not** relaxed
- Autonomous trigger extended (SOP §10.1): Director may self-trigger based on
  a time-pressure signal alone (not only explicit human request), but must
  announce the switch before executing — never silent

#### Andon Cord — universal emergency stop
- `pipeline_manager.py andon-pull/andon-clear/andon-status`; freezes `advance`
  pipeline-wide until cleared; AP mode cannot auto-clear (one of only two
  hard human-in-the-loop exceptions, alongside Checkpoint LA)

#### NASA Mission Control Go/No-Go — `final_compile` pre-flight check
- `quality_gate.py launch-check` (gate 8): polls Andon / stage completeness
  (now filtered by `problem_count`, see Fixed) / image existence / placeholder
  residue / anonymity / Los Alamos assumption-ledger integrity
- Mandatory before `final_compile` (new absolute-prohibition item, SOP §7)

#### Project Kaizen — post-verification quality-polish loop
- `pipeline_manager.py kaizen-assess/kaizen-round-start/kaizen-status`;
  4-dimension self-assessment (significance / robustness / assumptions /
  completeness, threshold 4.0/5), capped at 2 rounds, gated by the same
  objective time-budget signal as Skunk Works (opposite direction: adds
  rigor when time allows rather than relaxing it under pressure)
- Hard boundary vs. writing-style polish (§16): Kaizen may revise numeric
  conclusions and model content; style passes may not

#### Work Log — single-file complete session record
- `scripts/worklog.py` — append-only, Simplified Chinese,
  `CUMCM_Workspace/memory/worklog.md`; stage transitions / rework / Andon /
  Kaizen / gate results auto-logged from `pipeline_manager.py` and
  `quality_gate.py` at zero extra token cost; user messages and undocumented
  Agent decisions logged manually via `worklog.py append`

#### Citation Authenticity Verification & Shared Pool
- `scripts/cite_check.py` — `register` (dedup by DOI/URL/title into a shared
  `citations.bib` across sub-problems) / `verify` (DOI via CrossRef API, URL
  via HEAD request — catches hallucinated citations, not just format-shape
  matching) / `list` / `export-bibitems`
- `quality_gate.py` `lit` gate now prioritizes the verified citation pool over
  the legacy prose-regex scan; legacy path still works with a migration nudge
- Fixed: `export-bibitems` did not escape LaTeX special characters — a real
  DOI containing an underscore broke `xelatex` compilation with a fatal error

#### Writing-Style / "AI-Generated Feel" Reduction
- `scripts/style_check.py scan` — six objective, non-LLM checks: list-density
  in narrative sections, stock-phrase repetition, mechanical
  first/second/finally transition skeletons, sentence-length coefficient of
  variation, paragraph-length CV, cross-section n-gram repetition; thresholds
  informed by public research (mrshibly/Humanizer, Wikipedia:Signs of AI
  Writing, Pangram) and recalibrated against real Chinese academic writing
- SOP §16 writing protocol: plan-then-segment writing, ≤2 style-polish rounds;
  hard boundary — style polish may only change *how* something is said, never
  numeric conclusions (Kaizen's territory)
- Fixed: LaTeX comment lines (`%% ==== section divider ====`) were leaking
  into n-gram frequency analysis as false "repeated phrases"
- Fixed: overlapping sliding-window n-gram duplicates of the same longer
  phrase (e.g. three 6-char windows of one 8-char term) now merge into one
  finding instead of three

#### Official Format Compliance (SOP §17)
- CUMCM: `templates/latex_template.tex` synced to the 2026 format spec —
  electronic-version-compliant cover-page structure (title+abstract combined
  as page 1, page numbering starts there), `\tableofcontents` removed (official
  rule: no TOC), commented-out print-only 承诺书/编号页 block
- New anonymity heuristic gate `quality_gate.py anon-check` (self-referential
  / labeled-field phrase matching), wired into `launch-check`
- New `scripts/ai_usage_doc.py`: `generate` (builds a standalone
  《AI工具使用详情》PDF from `worklog.md` per the 2025-trial AI-tool-usage
  regulation's four required sections), `cite-format` (CUMCM reference-line
  formatter), `mcm-entry` (COMAP `Report on Use of AI Tools` entry formatter)
  — none of these auto-insert into the paper; declaring AI usage is a
  deliberate, manual decision by design
- MCM/ICM: `templates/mcm_template.tex` gets `\setcounter{tocdepth}{2}`
  (keeps the required TOC to ~1 page) and a commented-out
  `Report on Use of AI Tools` placeholder section (COMAP format, appended
  after the 25-page solution, not counted toward the limit)
- `compile_pdf.py` now reports page counts after a successful compile
  (PDF-bookmark-based body/appendix split) with contest-specific soft targets
  and hard-cap warnings — CUMCM body target 20–25 pages / hard cap 30
  (appendix unlimited); MCM/ICM hard cap 25 pages total including appendix
  code — and recommends compacting appendix core code first when over budget

#### §18 — Research domain-conventional visualization forms before drawing
- New `AutoMCM_SOP.md` §18 ("画图前先查领域惯例"): before designing any result
  figure, search (web-search, keywords abstracted per S3) for the
  conventional visualization form for that problem archetype — e.g.
  trajectory/geometry-optimization problems → 3D trajectory + key-moment
  annotation; coverage/siting/allocation → map/scatter + Gantt-style timeline;
  multi-objective/multi-scenario comparison → Pareto front or radar chart;
  sensitivity analysis → tornado chart or multi-parameter curve family;
  classification/clustering/ranking → heatmap or a re-sorted stacked bar
  chart. Findings recorded in `thought_process.md`; falling back to
  common-sense judgment is permitted when no clear convention is found, but
  — same spirit as §7's "never silently skip a failed check" — that fallback
  must also be recorded, never silently taken.
- Wired into `.claude/skills/auto-mcm/SKILL.md`'s 图表风格规范 section (new
  subsection preceding 标准用法) and cross-referenced across all three lean
  runtime bindings (`.opencode/`, `.dsh/`, `.agents/`).
- Codex binding's existing "known capability gap: no native web search"
  section extended to explicitly cover this new requirement too — the same
  underlying gap (no `WebSearch`/`WebFetch` tool) blocks the domain-convention
  research step, not just literature review; the existing "disclose at
  Checkpoint① rather than silently skip" guidance now applies to both.

#### Two new fully-autonomous demo cases (replacing the previous single showcase)
- `demo/2020C/` — real 2020 CUMCM Problem C (*Credit Strategy for Small and
  Micro Enterprises*), official attachments (~1.1M invoice rows) downloaded
  and verified from `mcm.edu.cn`. Full dsh headless run (zero human
  checkpoints) through all three sub-problems + sensitivity analysis:
  logistic-regression default-probability model (5-fold CV AUC 0.935),
  entropy-weight/TOPSIS cross-validation track, PSI transfer-stability check,
  KMeans industry-behavior clustering, expected-profit-maximizing credit
  allocation. 30 pages (21-page body), 18 figures, all 2D, zero 3D plots.
- `demo/2025A/` — 2025 CUMCM Problem A (smoke-screen decoy deployment),
  restyled end-to-end into a **NASA technical-report / orbital-mechanics
  chart theme** (white background, dense fine grid + bold major gridlines,
  black/white primary lines, NASA Blue `#0B3D91` / NASA Red `#FC3D21`
  reserved for key-annotation accents only, fully boxed axes) — implemented
  as a workspace-local override of `scripts/plot_style.py`'s palette/rcParams/
  `save()` grid post-processing, not a change to the repository's shared
  style module. 28 pages (20-page body), same modeling conclusions as before
  restyling.
- `demo/mind_reader_ui.png` — the Mind-Reader tool screenshot (previously
  nested inside the single demo's `CUMCM_Workspace/`) relocated to a
  case-independent top-level path, since it illustrates the tool, not either
  specific paper.

### Runtime Bindings
- New: DeepSeek Harness (`dsh`) binding — `.dsh/skills/auto-mcm/SKILL.md`
- New: opencode binding — `.opencode/skills/auto-mcm/SKILL.md`
- New: Codex CLI binding — `.agents/skills/auto-mcm/SKILL.md`
- All three verified via real executed tasks (not documentation inference),
  cross-checked through structured runtime session logs (`opencode export`,
  decompressed `.zstd` dsh session logs, plain-`.jsonl` Codex rollouts)

### Fixed
- **`templates/latex_template.tex` and `templates/mcm_template.tex` both
  failed to compile out of the box** — both loaded `\usepackage{natbib}`
  while their bibliography section used plain `\bibitem`/`\cite` (not
  natbib's `\citep`/`\citet`), which is a fatal incompatibility
  (`Package natbib Error: Bibliography not compatible with author-year
  citations`). Neither template body actually uses any natbib-specific
  command, so natbib was unnecessary; removed from both. Verified with a
  from-scratch standalone `xelatex` compile of each template (CUMCM: exit 0,
  6 pages, zero errors once a placeholder figure exists; MCM/ICM: confirmed
  the natbib error is gone, remaining failure is the separate, already-
  documented `mcmthesis.cls` external-package requirement). This bug predates
  this release — every fresh template compile would have hit it — and had
  only ever been patched ad hoc inside individual generated papers'
  `main.tex`, never at the template source; this is the first fix at the
  actual source. README prerequisites also updated to document the
  `mcmthesis` package requirement for the MCM/ICM template specifically
  (most minimal TeX Live installs don't ship it; CUMCM doesn't need it).
- `plot_style.py`: correlation-matrix heatmap used a one-directional
  sequential colormap for signed (−1…1) data instead of `diverging_cmap()` —
  negative and positive correlation were nearly indistinguishable at a
  glance; fixed.
- Two instances of a "single-x-tick stacked bar chart degenerates into a
  solid-color rectangle with no visible structure" bug, both triggered when
  an expected-profit-maximizing credit allocation concentrated almost
  entirely into one rating tier (2020C demo, `problem1_credit.py` and
  `problem2_credit.py`) — replaced with per-enterprise sorted horizontal bar
  charts (amount + PD annotated per bar), which is both correct rendering
  and more informative than the aggregate single bar it replaced.
- LaTeX verification-summary table (2025A demo `main.tex`) overflowed the
  page's right margin by ~415pt (~5.7in) — a plain `lcl` tabular with long
  cell text and no wrap points; fixed with `array` package `p{}`-width
  wrapped columns, plus `\allowbreak` inserted after underscores in
  monospace filenames (which otherwise have no natural line-break point and
  still overflow their column even when wrapping is enabled).
- 3D scene-overview and trajectory figures (2025A demo) had large dead
  whitespace bands where `set_box_aspect`'d axes were never tightened to
  their actual rendered content — added `plot_style.fit3d_axes()` (two-pass
  render + `get_tightbbox()`-based repositioning) and wired it into the
  affected `00_data_eda.py`/`problem1_geometry.py` figure functions; also
  replaced two 3D-space text labels that sat close together in this
  scenario's real geometry (and so collided under certain view angles) with
  projection-immune screen-space `text2D` anchors.
- Documented, and deliberately reverted rather than shipped: a third 3D
  inset panel + taller figure canvas intermittently caused
  `bbox_inches='tight'`'s save-time crop to drop unrelated existing labels
  from a sibling subplot on the same figure — reproduced twice independently
  (including after reducing label offsets), suspected to be an mplot3d
  `Text3D` bounding-box quirk rather than a usage error in this codebase;
  reverted to the previously-verified two-panel layout instead of risking a
  silent regression for a marginal enhancement.
- `gate_launch_check()` stage-completeness check now filters by
  `problem_count` — previously always scanned `model_1`–`model_3` regardless
  of actual sub-problem count, producing a false permanent NO-GO for any
  1- or 2-problem contest
- Hardcoded `/tmp/` absolute paths in `quality_gate.py` example commands
  replaced with in-workspace paths — broke under sandboxed runtimes'
  `external_directory` permission checks

### Testing
- Every bug above (degenerate allocation charts, dead 3D whitespace, table
  overflow, wrong colormap) was found by direct human/Claude visual
  inspection of the rendered PDF pages — none were caught by the dsh agent's
  own completion report, and none could have been: the model dsh was running
  (`deepseek-v4-flash`) has no image-input support, so its claimed "visual
  self-review" was necessarily only ever a file/pixel-level programmatic
  check, disclosed honestly in `worklog.md` rather than misrepresented.
- Multiple full real-agent pipeline runs (dsh, opencode) exercising the
  complete new addon set together, independently re-verified rather than
  trusting agent self-reports (PDF validity/page counts, `launch-check`
  re-run, `cite_check verify` re-run, session-log decompression for
  tool-call audit)
- Los Alamos genuinely self-triggered via multiple distinct criteria across
  runs (explicit "compare methods" problem wording, autonomous
  complexity judgment with no such wording); one run surfaced two genuine
  Checkpoint LA two-track conflicts (one directional contradiction, one
  Condorcet cycle) — resolved with fully documented headless-degradation
  reasoning; flagged as a known test-methodology limitation that Checkpoint
  LA's true human-wait path remains unverified in a genuinely interactive
  session

---

## [0.2.0] — 2026-05-03

### Added

#### `/draw-image` Skill — OpenAI gpt-image-2 图像生成
- New skill `.claude/skills/draw-image/SKILL.md` for generating flowcharts,
  architecture diagrams, and conceptual illustrations via OpenAI gpt-image-2.
- New script `scripts/draw_image.py` — CLI wrapper around the OpenAI Images API:
  - Supports `gpt-image-2` (default), `gpt-image-1.5`, `gpt-image-1`,
    `gpt-image-1-mini`, `dall-e-3`
  - Parameters: `--size` (any valid WxH for gpt-image-2, up to 3840px),
    `--quality` (low/medium/high/auto), `--output-format` (png/jpeg/webp),
    `--compression`, `--background`, `--moderation`
  - `--check` flag: probes authentication without generating anything
- Three-tier auth detection (in priority order) with explicit default-on/off behavior:
  1. `OPENAI_API_KEY` env var → OpenAI Python SDK path (token-based billing)
  2. Codex OAuth session detected (scans `~/.codex/auth.json` and related paths,
     `CODEX_AUTH_TOKEN` / `OPENAI_OAUTH_TOKEN` env vars) →
     **auto-enabled** without any configuration; routes to Codex CLI `$imagegen`
     (free within ChatGPT Plus/Pro subscription)
  3. Neither configured → **disabled by default**; graceful skip (exit code 2,
     not an error); pipeline continues with `\missingfigure{}` placeholder in LaTeX
- **Design intent**: Codex users get image generation out of the box; non-Codex
  users see the feature as off unless they explicitly supply an API key — no
  unexpected charges, no pipeline interruptions
- Skill documents: decision tree (when to use AI images vs. matplotlib),
  prompt engineering templates, LaTeX integration, pricing table, error guide

#### Multi-Agent Parallel Pipeline (AP Mode)
- `pipeline_manager.py` new flag and commands:
  - `init --problems N` — records sub-problem count; enables automatic AP
    multi-agent parallelism when N > 1; stored as `problem_count` in
    `pipeline.json`
  - `suggest-parallel` — inspects current pipeline state and outputs the next
    batch of stages that can be parallelized right now (exit 0 + space-separated
    stage list); exit 1 when nothing to parallelize (single problem or conditions
    not met). Two phases auto-detected:
    1. `data_preprocessing` approved → outputs all `model_N_build` stages
    2. All builds approved → outputs all `model_N_verify` stages
  - `parallel-start <s1> <s2> ...` — mark multiple stages `in_progress`
    simultaneously, enabling concurrent Agent execution
  - `parallel-status <s1> <s2> ...` — print a completion table for a stage group
  - `parallel-all-done <s1> <s2> ...` — exit 0 if all stages are `approved`,
    exit 1 otherwise (safe to use in shell conditionals)
- `pipeline_manager.py` new constant `PARALLEL_GROUPS` documenting which
  stages are safe to parallelize and their prerequisites
- `auto-mcm/SKILL.md` AP pipeline section updated:
  - `model_build + model_verify` entry now has a parallel decision gateway:
    calls `suggest-parallel` first; Path A (parallel) or Path B (sequential)
  - AP sub-Agent prompt template included inline with AP-mode self-approve step
  - `【多 Agent 并行策略】` section refactored into a concise reference with
    command quick-reference table; full steps moved to AP flow section
  - Background `draw-image` dispatch pattern with graceful skip
  - LaTeX section parallelization via `latex/sections/` fragments

#### Contest Git — 竞赛工作区版本控制
- New script `scripts/contest_git.py` — manages an independent Git repo inside
  `CUMCM_Workspace/` (separate from the AutoMCM-Pro tool repo):
  - `init` — creates the workspace repo with `.gitignore` (LaTeX intermediates
    excluded) and an initial commit; configures git identity automatically
  - `auto_commit(stage, mode, round_n)` — called by `pipeline_manager.py` after
    each `advance`; commits staged changes with semantic message
    `feat(<stage>): approved [AP]` or `fix(<stage>): rework rN approved`
  - `rework_start(stage, round_n)` — empty commit marking the rework entry point
    in the log, called on `rework`
  - `milestone_tag(name, message)` — annotated tag (overwrites if exists)
  - Auto-tagging: `latex_draft` approved → `draft-v1`, `final_compile` approved
    → `final-v1` (increments with review rounds)
  - Read-only queries: `log(n, oneline)`, `diff(ref1, ref2, stat_only)`,
    `status()`, `list_tags()`
  - Standalone CLI: `python scripts/contest_git.py init|log|diff|status|tag|tags`
- `pipeline_manager.py` integration:
  - `init --git` flag: enables contest git and calls `contest_git.init()`
  - `git_enabled` field persisted in `pipeline.json`
  - `advance` auto-commits on every stage approval
  - `rework` records a rework-start empty commit
  - New `contest-git` subcommand group: `log`, `diff`, `status`, `tag`, `tags`
- `auto-mcm/SKILL.md`: new **【竞赛工作区版本控制】** section with event/git-action
  table and usage examples

#### Skill Updates
- `cumcm-master/SKILL.md`: figure source decision tree (data vs. non-data);
  `/draw-image` integration in the figure-generation step
- `mcm-master/SKILL.md`: same figure decision tree in English
- `auto-mcm/SKILL.md`: `latex_draft` stage now documents draw-image option

### Changed

#### Security Fixes
- `pipeline_manager.py`: sanitize user-provided `--summary`/`--results`/
  `--concerns` before writing to eval log and review files — prevents
  injection of `[APPROVED]`/`[REWORK]` control markers via argument strings
- `pipeline_manager.py`: marker replacement in `human_intervention.md` now
  uses `str.replace(..., count=1)` — preserves full review history; prior
  approvals and reworks no longer silently overwritten
- `pipeline_manager.py`: `load()` now catches `json.JSONDecodeError` and
  exits with a clear recovery message instead of an uncaught exception
- `pipeline_manager.py`: emit `UserWarning` when `contest_git` module is
  unavailable instead of silently disabling all version-control features
- `contest_git.py`: `auto_commit` now calls `_scan_staged_for_secrets()`
  before every commit; blocks and warns if OpenAI keys (`sk-…`), GitHub
  tokens (`ghp_…`), AWS keys (`AKIA…`), or `password=`/`token=` patterns
  are found in staged diffs
- `contest_git.py`: `.gitignore` expanded to block `.env`, `*.key`, `*.pem`,
  `credentials.*`, `secrets.*`, `*_token*`, `config.local.*`

#### Automation & Reliability
- `pipeline_manager.py`: `--max-reworks N` flag on `init` (default 5);
  `cmd_rework` checks per-stage rework count and exits with code 2 if
  limit exceeded, preventing infinite repair loops
- `auto-mcm/SKILL.md` UX overhaul — zero command-line interaction for users:
  - Wake-up protocol now checks initialization state first; triggers
    **首次启动协议** (first-launch protocol) when workspace is not yet set up
  - First-launch protocol: agent asks for file paths via natural language
    (AskUserQuestion), reads the problem to auto-detect sub-problem count and
    contest type, then runs all init commands silently (setup_workspace.py +
    pipeline_manager.py init with --problems N --git)
  - AP mode checkpoints: replaced raw command output with natural language
    progress reports after each stage; no user input needed
  - MANUAL mode: user provides specs and approvals in natural language; agent
    translates internally to pipeline commands; removed "输入继续" terminal
    instruction
  - Rework protocol: user states changes in natural language; agent writes to
    human_intervention.md and executes rework command silently
- `README.md` "How to Use" section rewritten for zero-command UX:
  - Removed all `pipeline_manager.py init` instructions from user-facing steps
  - Added AP mode and MANUAL mode natural language dialogue examples
  - Updated English section to match
- New script `scripts/quality_gate.py` — hard-enforced 4-gate quality CLI
  (not behavioral rules): literature reference count (≥2 per sub-problem),
  numerical sanity scan (inf/nan/1e200+), structured PASS/FAIL report parsing,
  physical-constant cross-problem consistency check; subcommands
  `verify / sanity / lit / consist / all`; exit codes 0=pass, 1=fail, 2=skip
- New script `scripts/security_check.py` — hard-enforced security CLI:
  path traversal prevention (`check_paths`), env-variable leak detection
  (`check_env_not_leaked`), workspace secret scan (`scan_files_for_secrets`,
  `scan_workspace_all`); 6 secret patterns (OpenAI, Anthropic, GitHub, AWS,
  password literals, generic API keys); output auto-redacted to ≤20 chars
- `auto-mcm/SKILL.md`: **【建模质量门控】** updated — now documents exact
  `python scripts/quality_gate.py` invocations for every pipeline moment
  (build pre-gate, build post-gate, verify gate, consistency gate); structured
  `===VERIFICATION REPORT===` contract; LaTeX 3-attempt retry loop
- `auto-mcm/SKILL.md`: new **【安全规程】** section — API key protection,
  file path validation via `security_check.py path`, external-service query
  abstraction, rework-limit user notification, secret-commit interception
- `auto-mcm/SKILL.md`: dependency auto-check step added to wake-up protocol
- `pipeline_manager.py` docstring updated to list all new commands

### Removed
- `demo/multi_agent_demo/` — development-only test case (verified and removed
  after successful end-to-end run: 22/22 verifications passed, PDF compiled,
  gpt-image-2 flowchart generated)

---

## [0.1.0-beta] — 2026-03-14

### Added
- Initial release of AutoMCM-Pro
- `/auto-mcm`, `/cumcm-master`, `/mcm-master` skills
- AP / MANUAL dual-mode pipeline
- GitOps state machine (`pipeline_manager.py`) with 8 commands
- Mandatory self-verification protocol (verify_*.py for every solver)
- Mind-Reader real-time thought visualization (FastAPI + WebSocket)
- Docker environment (Python + TeX Live)
- CUMCM and MCM/ICM LaTeX templates
- Demo: CUMCM 2025 Problem A (11 stages, 144 verifications, ~1h34m runtime)
