# Agent Instructions for MPCWithGenerativeArt

Use this document when working on the **MPCWithGenerativeArt** codebase.

---

## Tone and Voice

- Be concise and technical.
- Explain design decisions and technical rationale clearly without filler words.
- Follow ASD-STE100 Simplified Technical English (STE) principles for written prose: active voice, short sentences, no marketing adjectives, and no contractions.

---

## Issue Tracking

This project uses **bd (beads)** for all issue tracking.
Run `bd prime` for workflow context.

### Essential Commands
- `bd ready`: Find unblocked work.
- `bd create --title="Title" --description="Details" --type=task|bug|feature --priority=2`: Create a new issue.
- `bd update <id> --claim`: Claim an issue before starting work.
- `bd close <id> --reason="Explanation"`: Mark an issue complete.
- `bd dolt push`: Push beads database to remote (when authorized).

---

## Architecture Overview

MPCWithGenerativeArt is a FastAPI and Vanilla JavaScript web application that generates custom print-ready card decks for MakePlayingCards.

```
MPCWithGenerativeArt/
├── backend/
│   ├── app.py           # FastAPI application, routes, SSE streaming, settings persistence
│   ├── parser.py        # Deck text parser (supports tabs, quantities, and global style prompts)
│   ├── scryfall.py      # Scryfall API client with disk caching and rate limiting
│   ├── generator.py     # Multi-provider async image generators with procedural fallbacks
│   ├── compositor.py    # CV template matching, text box masking, and 800 DPI bleed scaling
│   └── mpc_autofill.py  # MakePlayingCards XML generator, ZIP packager, and JS injector
├── frontend/
│   ├── index.html       # Single page application markup
│   ├── favicon.ico      # Multi-resolution website icon
│   ├── css/style.css    # Dark UI styling
│   └── js/
│       ├── app.js       # UI state, SSE event listeners, deck grid rendering
│       └── mpc_injector.js # Browser console script for autofilling MakePlayingCards orders
├── tests/               # Unit and integration test suites
├── cache/scryfall/      # Cached Scryfall frame and art images
└── output/cards/        # Generated 800 DPI card images
```

---

## Key Backend Modules

1. **`backend/parser.py`**:
   - Parses deck lines formatted as `[Copies] [CardName] ([SetCode]) [CollectorNumber]\t[Prompt]`.
   - Extracts top-level `# [global style prompt]` lines and combines them with card prompts.
2. **`backend/scryfall.py`**:
   - Queries Scryfall REST API by set code and collector number.
   - Caches frame images (`.png`) and official art crops (`.jpg`) locally in `cache/scryfall/` to respect Scryfall rate limits.
3. **`backend/generator.py`**:
   - Abstract base class `BaseImageGenerator` with pluggable backends:
     - `GrokImageGenerator` (xAI `grok-imagine-image-2.0`)
     - `JanusImageGenerator` (DeepSeek Janus-Pro-7B via Gradio / Hugging Face Spaces)
     - `GeminiImageGenerator` (Google `imagen-3.0-generate-002`)
     - `OpenAIImageGenerator` (OpenAI `dall-e-3`)
     - `PerchanceImageGenerator` (Headless Playwright Chromium)
     - `MockProceduralGenerator` (Deterministic offline fallback)
   - Configurable timeout and read timeout controls with graceful fallback hierarchy.
4. **`backend/compositor.py`**:
   - Locates art box bounding box using multi-scale sliding-window template search.
   - Identifies card layout type (Creature, Planeswalker, Battle, Showcase, Inverted, Borderless).
   - Generates precision binary exclusion mask for title bars, type lines, rules boxes, and stats badges.
   - Applies soft box-blur edge feathering.
   - Scales card frames by `0.90` (5% bleed margin) and renders at MakePlayingCards standard 800 DPI poker dimensions (2184x2968 pixels).
5. **`backend/mpc_autofill.py`**:
   - Generates `cards.xml` adhering to MakePlayingCards autofill standards.
   - Packages ZIP files containing XML and print-ready card images.
   - Serves the in-browser MakePlayingCards injector script.

---

## Tooling and Testing

### Running Tests
Execute the test suite using Python's built-in `unittest` runner:

```bash
python -m unittest tests/test_grok.py tests/test_janus.py tests/test_api.py tests/test_pipeline.py
```

### Environment Configuration
- Set `TESTING=true` or `ENV_FILE=none` during automated testing to avoid modifying `.env`.
- Use `GENERATOR_PROVIDER=mock` for instant deterministic test execution without network calls.

---

## Development Constraints and Guidelines

- **Preserve Existing Comments**: Do not remove comments or docstrings unrelated to your changes.
- **Scryfall Rate Limits**: Always route Scryfall requests through `scryfall_client` to avoid IP blocking.
- **Fail Gracefully**: If an AI image generator times out or encounters API limits, fall back to procedural generation without crashing the generation pipeline.
- **Scope Discipline**: Read only the files necessary for the assigned task.
- **Knowledge Persistence**: When introducing reusable patterns or algorithms, update `ROMzombieSkillLibrary`.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
