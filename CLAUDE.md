# Frank Energie – Home Assistant custom integration

## Project
- Integration code: `custom_components/frank_energie/` (see Module map below)
- Library: `python-frank-energie` (version pinned in `manifest.json`)
- Tests: `tests/` with `pytest-homeassistant-custom-component`
- CI: flake8 (max line 120, complexity 10) + pytest, Python 3.14 (`.github/workflows/ci.yaml`)
- Local environment: `.venv` (Python 3.14, gitignored). Create/update it with the `setup-dev` skill
  (`.claude/skills/setup-dev/scripts/setup_dev.sh`); run tools as `.venv/bin/pytest` and `.venv/bin/flake8`.
  Library sources: `.venv/lib/python3.14/site-packages/{python_frank_energie,homeassistant}/`.
- Hooks (`.claude/hooks/`, wired in `.claude/settings.json`): flake8 runs on every edited `.py` file and reports
  errors immediately (fix them before continuing); whole-disk searches (`find /`, `find ~`, `locate`, …) are blocked.

## Module map
Go straight to the right file and its test; read library code only for the functions named here.
Paths are relative to `custom_components/frank_energie/`; tests are in `tests/`, shared helpers in `tests/utils.py`
and `tests/conftest.py`. Library sources: `.venv/lib/python3.14/site-packages/python_frank_energie/`
(`frank_energie.py` = API client, `models.py` = `PriceData`/`Price`/`MarketPrices`).

| File | What it does | Tests | Depends on (library / HA) |
|---|---|---|---|
| `__init__.py` | Entry setup/unload, site discovery for legacy entries, removes entities of disabled sensor groups, creates coordinators (analysis, usage, contract and statistics import only when enabled), keeps the cost data sources in sync (`_async_setup_cost_data_sync`), registers the action | `test_init.py`, `test_sensor_groups.py` | `FrankEnergie.UserSites` |
| `config_flow.py` | Login, site choice, reauth (`wrong_account`), reconfigure, options flow (page 1: time zone + sensor groups; page 2 `analysis` with two sections, flattened before saving) | `test_config_flow.py` | `FrankEnergie.login/UserSites`, `OptionsFlowWithReload` |
| `coordinator.py` | Fetches prices/costs/invoices hourly, public fallback, token renewal + persistence, stale data, Amsterdam market day, `prices_tzinfo` | `test_coordinator.py` | `prices`, `user_prices`, `country_prices`, `user_country`, `month_summary`, `invoices`, `PriceData.__add__` |
| `usage.py` | Usage coordinator: yesterday's usage/costs and this month's insights every 3 hours, per enabled group; keeps previous data on failure | `test_usage.py`, `test_usage_sensors.py` | `period_usage_and_costs`, `month_insights` |
| `contract.py` | Contract coordinator: contract price resolution state every 6 hours | `test_contract.py` | `user`, `contract_price_resolution_state` |
| `energy_statistics.py` | Imports hourly usage and costs as external Energy dashboard statistics (first run 30 days, then every 3 hours) | `test_energy_statistics.py` | `period_usage_and_costs`, recorder statistics |
| `sensor.py` | All sensor descriptions (current/daily/upcoming/costs, daily/monthly usage) and the analysis sensors; quarter-hour refresh | `test_sensor.py`, `test_usage_sensors.py` | `PriceData.current_hour/today_*/tomorrow_*/upcoming_*/asdict` |
| `binary_sensor.py` | Analysis binary sensors (cheap price now, cheapest period now) | `test_price_analysis.py` | — |
| `analysis.py` | Pure calculations: levels, cheapest period, windows, solar per slot | `test_analysis.py` | — (no HA, no library) |
| `price_analysis.py` | Analysis coordinator: reads prices + solar, computes and caches results, debounced refresh | `test_price_analysis.py` | `DataUpdateCoordinator` |
| `solar_forecast.py` | Best-effort solar forecast from HA energy platforms (timeout, never raises) | `test_solar_forecast.py` | `energy.websocket_api.async_get_energy_platforms` |
| `services.py` + `services.yaml` | `frank_energie.get_prices` action | `test_services.py` | — |
| `diagnostics.py` | Redacted diagnostics download | `test_diagnostics.py` | `async_redact_data` |
| `sites.py` | Delivery-site filtering and titles | `test_init.py`, `test_config_flow.py` | `DeliverySite` |
| `device.py` | Shared `DeviceInfo` (identifiers must not change) | — | — |
| `const.py` | Constants, option keys and defaults; sensor groups: `SENSOR_GROUP_BY_KEY` (entity key → group), `enabled_groups(entry)` and `key_enabled(key, groups)` (the one place that decides group membership) | `test_sensor_groups.py` | — |
| `strings.json`, `translations/en.json`, `translations/nl.json` | UI texts (keep the three in sync) | `test_translations.py` | — |

## Roles
- **You (main session, Opus 5.5)**: architect, problem solver and orchestrator.
  Do not write production code or tests yourself for non-trivial changes.
- **developer** (Sonnet 5.5): implements code from your spec, including its unit and integration tests.
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

## Scope discipline
Agents (and the orchestrator) change only what the task requires: no unrequested improvements, features or
abstractions; unrelated issues are reported, not fixed. Adapted from the Karpathy guidelines
(github.com/multica-ai/andrej-karpathy-skills); the full rules are in `.claude/agents/developer.md`.

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
- PRs and releases: use the `/release` skill (`/release pr`, `/release publish [vX.Y.Z]`); only when I ask.
- Never call the real Frank Energie API in tests; never log tokens or credentials.
- Home Assistant MCP (`home-assistant`, user-scoped, connected to my real Home Assistant): use it only to
  verify the integration (states, attributes, history, logs, integration info). Never switch devices, change
  configuration, automations, dashboards or HACS, reload or restart unless I ask; those tools require my approval,
  and deleting tools are blocked. Never paste the HA URL or token anywhere. Subagents don't use it.
