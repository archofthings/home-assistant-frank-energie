# Frank Energie – Home Assistant custom integration

## Project
- Integration code: `custom_components/frank_energie/` (config_flow, coordinator, sensor, const)
- Library: `python-frank-energie` (version pinned in `manifest.json`)
- Tests: `tests/` with `pytest-homeassistant-custom-component`
- CI: flake8 (max line 120, complexity 10) + pytest, Python 3.14 (`.github/workflows/ci.yaml`)
- Local environment: `.venv` (Python 3.14, gitignored). Create/update it with the `setup-dev` skill
  (`.claude/skills/setup-dev/scripts/setup_dev.sh`); run tools as `.venv/bin/pytest` and `.venv/bin/flake8`.
  Library sources: `.venv/lib/python3.14/site-packages/{python_frank_energie,homeassistant}/`.

## Roles
- **You (main session, Opus 5.5)**: architect, problem solver and orchestrator.
  Do not write production code or tests yourself for non-trivial changes.
- **developer** (Sonnet 5): implements code from your spec, including its unit and integration tests.
- **tester** (Sonnet 5): checks the tests against the spec, fills gaps, adds regression tests and revert checks.
- **reviewer** (Opus 5.5, read-only): reviews the final change.

## Workflow
1. Analyse the request and relevant code; produce a design/spec (use plan mode for bigger changes).
   The spec must include: files to change, functions/classes and signatures, behaviour,
   edge cases, and acceptance criteria. Wait for my approval on bigger designs.
2. Delegate implementation to `developer` with the full spec (subagents do not see this conversation).
3. Delegate test verification to `tester`, passing the spec and the developer's summary. Keep the test level
   as it is (unit + integration tests with mocked API, regression/revert checks); no extra test types.
4. If tests fail: diagnose the root cause yourself, then send a targeted fix spec to `developer`
   (or to `tester` if the test is wrong). Repeat 3–4.
5. Delegate review to `reviewer` with the spec. Send Critical/Warning items back to `developer`.
6. Summarise to me: what changed, test results, review verdict, anything I need to decide.

## Test budget
Keep tests lean; they are read and run by every agent, so size costs tokens.
- Per change: one test for the main behaviour, plus tests only for edge/error cases the spec explicitly names.
- Prefer `pytest.mark.parametrize` over copied tests; no tests for simple mappings, constants or text files
  (one translations test checks all files).
- `tester` only runs for larger features; revert checks only for bug fixes.
- `reviewer` flags missing tests only when important behaviour is untested (no "nice to have" gaps).
- While working, run only the relevant test file; run the full suite once before committing.
- Small fixes: no tester step; the orchestrator checks the result instead of a full review.

## When to skip the pipeline
Small, single-file changes (typo, constant, one-line fix): do it directly, then run flake8 and pytest.

## Rules
- `developer` and `tester` may commit locally after each completed task, once flake8 and pytest pass:
  one logical change per commit, a clear imperative message, only the files for that task
  (never `git add -A`). No amending or rewriting existing commits.
- `CLAUDE.md` and `.claude/` (agents, shared `settings.json`) are tracked in the repo; only the orchestrator
  changes and commits them, in their own commit. `.claude/settings.local.json` stays untracked.
- Never commit on `main` directly: work on a feature branch (the orchestrator creates it).
- Only the orchestrator pushes, and only when I explicitly ask; `git push` always requires my approval
  (`ask` rule in `.claude/settings.json`). Subagents never push.
- GitHub: use the `gh` CLI (logged in as archofthings; repo `archofthings/home-assistant-frank-energie`).
  Read-only commands (`gh pr view/list/diff/checks`, `gh run`, `gh release view/list`) are allowed; anything that
  publishes (PRs, comments, releases, `gh api`, workflow runs) needs my approval and is only done when I ask.
  Subagents never run `gh` commands that publish.
- Never call the real Frank Energie API in tests; never log tokens or credentials.
