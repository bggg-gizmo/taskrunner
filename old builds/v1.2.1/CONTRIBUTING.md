# Contributing to Task Runner

Task Runner is developed by **Background Gremlin Group — Creating Unique Tools for Unique Individuals**.

Contributions must preserve existing behavior unless a change is explicitly agreed upon. Do not remove workflow actions, saved schema fields, scheduler features, audio cues, icons, or GUI controls as a side effect of unrelated work.

## Development and validation

1. Use Python 3.11–3.13 x64 on Windows for native integration tests. Source preparation can be done on Linux, but it cannot certify native Windows UI Automation.
2. Read `docs/USER_GUIDE.md`, `BUILD_AUDIT.md`, `WINDOWS_ACCEPTANCE.md`, and `COORDINATION_LOG.md` before editing.
3. Run `python -m pytest tests -q` and `python -m compileall -q task_runner scripts tests launcher.py`.
4. Run `python scripts/prepublish_audit.py` before proposing changes.
5. For Windows builds, use `BUILD_WINDOWS.cmd`. The script checks reusable user-level dependencies, runs tests, installs shared Chromium, builds the EXE and runs a frozen-runtime self-test.
6. Add regression tests for changed behavior, especially timing/retries, window-focus transitions, clipboard restoration, accidental file overwrites, scheduler concurrency, and browser extraction.
7. Do not commit logs, task data, browser profiles, local screenshot captures, keys, or EXE build directories. Use sanitized data in issues and pull requests.

## GitHub usage

Pull requests are welcome for review. Do not introduce GitHub Actions workflows that cost money or credits. Dependabot configuration proposes package updates only; nothing automatically compiles Windows EXEs or publishes a release. Maintainers review dependency changes and perform actual Windows build acceptance before release.

## Public-domain and third-party assets

Use only assets that you created, own, or are permitted to redistribute. Do not replace the shipped original icon or retro sound effects without explicit review. The repository has no open-source license until its owner selects one; public visibility alone does not grant reuse rights.
