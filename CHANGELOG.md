# Changelog

## 1.2.1 hardening candidate — repository preparation (unreleased)

- Preserve the full 1.2.1 GUI, screenshot workflow, original audio, icon, build scripts and action catalog.
- Stage UTF-8 file replacements and file copies atomically, so incomplete writes/copies cannot first destroy the old file.
- Add a Settings → Backup task database control using SQLite's online backup and integrity check.
- Prevent a late/recovered worker from overwriting the state of a newer execution.
- Provide schema-backed portable job-export documentation and an action-catalog synchronization test.
- Add a public GitHub preparation package: `.gitignore`, `.gitattributes`, `.editorconfig`, issue forms, Dependabot configuration, pull request template, branch ruleset proposal, security policy, contributor guide, architecture notes and prepublication audit.
- No paid or credit-consuming GitHub Actions have been added; no remote repository has been modified.

## 1.2.1 — corrective Windows integration

- Independent native Unicode typing and cursor API isolation.
- Delayed desktop screenshot capture of transient right-click menus.
- Direct wizard shortcuts for dropdown and scrolling text actions, waits and select controls.
- Configurable click verification, retry and settling defaults, and a bulk timing editor for saved tasks.
- Startup and exit sound cues, governed by the existing sound toggle.
- Optional auto-minimize while a manual desktop workflow executes.

## 1.2.0 — extended action catalog

- Browser and Windows dropdown inspection, scrolling text capture and intelligent waits.
- Builder recovery from pip wheel-cache permission issues.
- Background Gremlin Group developer attribution and Windows version resource metadata.

## Initial integration line

- Native Windows PySide6 dashboard and visual workflow wizard, Playwright/Beautiful Soup, desktop automations, SQLite history, scheduling, build scripts, original vaporwave assets and sound effects.

- Added `CHECK_GITHUB_READINESS.cmd`, an entirely local pre-publication scan/compile/test command.
- Made GUI JSON exports serialize `enabled` as a boolean and kept the portable JSON Schema backward-compatible with existing 0/1 export values.
