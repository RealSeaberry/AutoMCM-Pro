# Changelog

All notable changes to AutoMCM-Pro are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Version scheme: [Semantic Versioning](https://semver.org/).

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
