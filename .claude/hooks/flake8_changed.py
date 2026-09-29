#!/usr/bin/env python3
"""PostToolUse hook: run flake8 (CI settings) on a Python file right after it was edited or written.

Reads the hook payload from stdin. On lint errors, prints them to stderr and exits 2, so Claude sees them
and fixes the file straight away. Does nothing for non-Python files, files outside the project, or when
.venv/bin/flake8 is missing (run the setup-dev skill to create it).
"""
import json
import os
import subprocess
import sys

try:
    payload = json.load(sys.stdin)
except ValueError:
    sys.exit(0)

file_path = (payload.get("tool_input") or {}).get("file_path") or ""
project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
flake8 = os.path.join(project, ".venv", "bin", "flake8")

if not file_path.endswith(".py") or not os.path.isfile(file_path) or not os.path.exists(flake8):
    sys.exit(0)

real_file = os.path.realpath(file_path)
real_project = os.path.realpath(project)
if not real_file.startswith(real_project + os.sep) or f"{os.sep}.venv{os.sep}" in real_file:
    sys.exit(0)

result = subprocess.run(
    [flake8, "--max-complexity=10", "--max-line-length=120", real_file],
    cwd=real_project,
    capture_output=True,
    text=True,
)
if result.returncode != 0 and result.stdout.strip():
    print(f"flake8 found issues in {os.path.relpath(real_file, real_project)} (CI will fail on these):", file=sys.stderr)
    print(result.stdout.strip(), file=sys.stderr)
    sys.exit(2)
sys.exit(0)
