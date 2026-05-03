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
- `scripts/draw_image.py`: default model upgraded from `gpt-image-1` to
  `gpt-image-2`; `--size` changed from fixed choices to free-form string to
  support gpt-image-2's flexible resolution system
- `README.md`: added `/draw-image`, multi-agent, and contest version control
  sections (Chinese + English); updated project structure tree; added optional
  `openai>=1.0` prerequisite; added version badge
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
