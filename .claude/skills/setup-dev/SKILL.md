---
name: setup-dev
description: Create or update the project's Python 3.14 test environment in .venv (requirements.txt + pytest-cov) and print the paths to pytest, flake8 and the installed library sources. Use when .venv is missing, when requirements.txt changed, or before running tests or flake8 in a fresh checkout or session.
---

# Set up the development environment

Run the setup script from the repository root:

```bash
.claude/skills/setup-dev/scripts/setup_dev.sh
```

- It creates `.venv` with Python 3.14 if it doesn't exist.
- It installs `requirements.txt` plus `pytest-cov`, but only when `requirements.txt` changed since the last run
  (tracked in `.venv/.requirements.sha256`). Pass `--force` to reinstall anyway.
- It prints the paths to use afterwards, including where the `python_frank_energie` and `homeassistant`
  sources are installed. Read library code from those paths; never search the whole filesystem.

After setup, always use the venv's tools:

```bash
.venv/bin/pytest -q -p no:cacheprovider                     # full suite
.venv/bin/pytest -q -p no:cacheprovider tests/test_sensor.py  # one file
.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
.venv/bin/flake8 . --count --max-complexity=10 --max-line-length=120 --statistics
.venv/bin/pytest -q -p no:cacheprovider --cov=custom_components/frank_energie --cov-branch --cov-report=term
```

Delete `.coverage` after a coverage run; never commit it or `.venv`.

If the script fails because `python3.14` is missing, tell the user; don't try to install Python yourself.
