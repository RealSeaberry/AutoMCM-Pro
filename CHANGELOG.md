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
- Three-tier auth detection (in priority order):
  1. `OPENAI_API_KEY` env var → OpenAI Python SDK path
  2. Codex OAuth session (scans `~/.codex/auth.json` and related paths,
     `CODEX_AUTH_TOKEN` / `OPENAI_OAUTH_TOKEN` env vars) → routes to
     Codex CLI `$imagegen`
  3. Neither configured → **graceful skip** (exit code 2, not an error);
     pipeline continues with `\missingfigure{}` placeholder in LaTeX
- Skill documents: decision tree (when to use AI images vs. matplotlib),
  prompt engineering templates, LaTeX integration, pricing table, error guide

#### Multi-Agent Parallel Pipeline
- `pipeline_manager.py` new commands:
  - `parallel-start <s1> <s2> ...` — mark multiple stages `in_progress`
    simultaneously, enabling concurrent Agent execution
  - `parallel-status <s1> <s2> ...` — print a completion table for a stage group
  - `parallel-all-done <s1> <s2> ...` — exit 0 if all stages are `approved`,
    exit 1 otherwise (safe to use in shell conditionals)
- `pipeline_manager.py` new constant `PARALLEL_GROUPS` documenting which
  stages are safe to parallelize (`model_builds`, `model_verifies`,
  `latex_sections`) and their prerequisites
- `auto-mcm/SKILL.md` new section **【多 Agent 并行策略】**:
  - Parallelization opportunity table
  - `parallel-start` → N sub-Agent spawn → `parallel-all-done` workflow
  - Sub-Agent prompt template for `model_N_build + verify`
  - Background `draw-image` dispatch pattern with graceful skip
  - LaTeX section parallelization via `latex/sections/` fragments

#### Skill Updates
- `cumcm-master/SKILL.md`: figure source decision tree (data vs. non-data);
  `/draw-image` integration in the figure-generation step
- `mcm-master/SKILL.md`: same figure decision tree in English
- `auto-mcm/SKILL.md`: `latex_draft` stage now documents draw-image option

### Changed
- `scripts/draw_image.py`: default model upgraded from `gpt-image-1` to
  `gpt-image-2`; `--size` changed from fixed choices to free-form string to
  support gpt-image-2's flexible resolution system
- `README.md`: added `/draw-image` and multi-agent sections (Chinese + English);
  updated project structure tree; added optional `openai>=1.0` prerequisite;
  added version badge
- `pipeline_manager.py` docstring updated to list new parallel commands

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
