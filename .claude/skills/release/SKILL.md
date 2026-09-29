---
name: release
description: Prepare and publish changes of the Frank Energie integration on GitHub. "/release pr" writes the pull request description for the current branch and creates the PR; "/release publish [version]" writes the release notes and creates the GitHub release that HACS installs from. User-invoked only, because it publishes.
disable-model-invocation: true
argument-hint: "pr | publish [vX.Y.Z]"
---

# Release workflow

Repository: `archofthings/home-assistant-frank-energie` (remote `origin`), default branch `main`.
Every command that publishes (`git push`, `gh pr create`, `gh release create`) needs the user's approval
through the permission prompt. Never work around a denied prompt.

Arguments: `$ARGUMENTS`. If empty, ask whether the user wants `pr` or `publish`.

## Mode `pr`: create a pull request for the current branch

1. **Check the branch.** It must not be `main`. `git status --short` must be clean; if not, stop and report.
   `git fetch -q origin`, then `git log --oneline origin/main..HEAD`. If there are no commits, stop.
2. **Check quality.** Run once:
   - `.venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`
   - `.venv/bin/flake8 . --count --max-complexity=10 --max-line-length=120 --statistics`
   - `.venv/bin/pytest -q -p no:cacheprovider`
   If `.venv` is missing, run the `setup-dev` skill first. If anything fails, stop and report; don't create the PR.
3. **Collect the facts** from `git log origin/main..HEAD` (subjects and bodies) and
   `git diff --stat origin/main...HEAD`. Read changed files only where the commit messages aren't enough.
4. **Write the description** with `templates/pr.md`:
   - Describe only what the commits actually change. No claims that weren't verified.
   - Mention user-visible behaviour changes and upgrade notes (defaults, entity IDs, attributes, options).
   - Testing: the real numbers from step 2. Write "Not tested against a live Home Assistant instance" unless
     the change was verified through the `home-assistant` MCP in this session; then say what was checked.
   - Leave out sections that don't apply.
5. **Show the title and description to the user** and wait for confirmation or edits.
6. **Publish:** if the branch isn't on `origin` yet, `git push -u origin <branch>`. Then
   `gh pr create --base main --head <branch> --title "<title>" --body-file <file>`
   (write the body to a file in the scratchpad). Report the PR URL.

## Mode `publish`: create a release from `main`

1. `git fetch -q origin`. Find the latest release: `gh release list --limit 5`.
   List what's new: `git log --oneline <latest tag>..origin/main` and the merged PRs
   (`gh pr list --state merged --limit 10`).
2. **Version.** If the user passed one, use it (prefix `v`, three parts, e.g. `v1.3.1`). Otherwise suggest one:
   - major: breaking changes (removed entities/attributes, changed entity IDs, new minimum HA version)
   - minor: new features (entities, options, actions)
   - patch: only fixes and docs
   Ask the user to confirm the version and whether it should be a pre-release.
3. **Check CI on main:** `gh run list --branch main --workflow ci.yaml --limit 1`. If the last run failed, stop and report.
4. **Write the release notes** with `templates/release.md`: user-facing, based on the merged PRs.
   Internal refactoring, tests and tooling (`.claude/`, `CLAUDE.md`) are left out unless they matter to users.
   Always include upgrade notes (breaking changes or "No breaking changes").
5. **Show the tag, title and notes to the user** and wait for confirmation or edits.
6. **Publish:** `gh release create <tag> --target main --title "<title>" --notes-file <file> [--prerelease]`.
7. **Verify:** the release workflow builds `frank_energie.zip` and attaches it, which HACS needs.
   Check `gh run list --workflow release.yaml --limit 1` and, once it has finished,
   `gh release view <tag> --json assets`. Report whether `frank_energie.zip` is attached; if the run failed,
   show `gh run view <id> --log-failed` output (last lines only).

## Style
- English, clear and specific; no marketing language.
- Tables for entities and options; short bullets elsewhere.
- PR descriptions end with the line: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
