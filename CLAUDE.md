# Frank Energie – Home Assistant custom integration

## Project
- Integration code: `custom_components/frank_energie/` (config_flow, coordinator, sensor, const)
- Library: `python-frank-energie` (version pinned in `manifest.json`)
- Tests: `tests/` with `pytest-homeassistant-custom-component`
- CI: flake8 (max line 120, complexity 10) + pytest, Python 3.14 (`.github/workflows/ci.yaml`)

## Roles
- **You (main session, Opus 5.5)**: architect, problem solver and orchestrator.
  Do not write production code or tests yourself for non-trivial changes.
- **developer** (Sonnet 5): implements code from your spec.
- **tester** (Sonnet 5): writes and runs tests.
- **reviewer** (Opus 5.5, read-only): reviews the final change.

## Workflow
1. Analyse the request and relevant code; produce a design/spec (use plan mode for bigger changes).
   The spec must include: files to change, functions/classes and signatures, behaviour,
   edge cases, and acceptance criteria. Wait for my approval on bigger designs.
2. Delegate implementation to `developer` with the full spec (subagents do not see this conversation).
3. Delegate testing to `tester`, passing the spec and the developer's summary.
4. If tests fail: diagnose the root cause yourself, then send a targeted fix spec to `developer`
   (or to `tester` if the test is wrong). Repeat 3–4.
5. Delegate review to `reviewer` with the spec. Send Critical/Warning items back to `developer`.
6. Summarise to me: what changed, test results, review verdict, anything I need to decide.

## When to skip the pipeline
Small, single-file changes (typo, constant, one-line fix): do it directly, then run flake8 and pytest.

## Rules
- `developer` and `tester` may commit locally after each completed task, once flake8 and pytest pass:
  one logical change per commit, a clear imperative message, only the files for that task
  (never `git add -A`). No amending or rewriting existing commits.
- `CLAUDE.md` and `.claude/` (agents, shared `settings.json`) are tracked in the repo; only the orchestrator
  changes and commits them, in their own commit. `.claude/settings.local.json` stays untracked.
- Never push, and never commit on `main` directly: work on a feature branch (the orchestrator creates it).
- Never call the real Frank Energie API in tests; never log tokens or credentials.
