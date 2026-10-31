# Task Runner architecture

## Modules and boundaries

- `task_runner/gui.py`: PySide6 dashboard, task wizard, action editor, screenshot selection, logs, Settings, scheduler buttons and local SQLite backup button. The current visual design remains intact.
- `task_runner/actions.py`: single action catalog and default step parameters. `scripts/generate_workflow_schema.py` derives the JSON Schema used for portable exports.
- `task_runner/flow.py`: preflight validation and control-flow compilation; malformed blocks are rejected before running earlier destructive steps.
- `task_runner/executor.py`: ordered execution, variable interpolation, retries, delays, verification, cancellation, event journaling and action dispatch.
- `task_runner/collection.py`: Playwright document/dropdown handling and Windows UI Automation data capture.
- `task_runner/winmouse.py` and `wininput.py`: dedicated Windows mouse/Unicode input modules that avoid incompatible shared cursor API signatures.
- `task_runner/fileops.py`: staged replacement for UTF-8 output and copied files, retaining old content if writing or staging a copy fails.
- `task_runner/store.py`: SQLite WAL persistence, cross-process atomic claims, execution journals, stale-worker recovery, and consistent online database backup.
- `task_runner/runner.py`: source/frozen launch paths, detached child workers, stop-signal files and Windows Task Scheduler integration.
- `task_runner/scheduling.py`: local-time schedule calculation, stored in UTC. Second-level polling requires the GUI open; Windows heartbeat remains one minute.
- `task_runner/diagnostics.py`: packaged-runtime self-test, including browser/runtime asset verification.

## Data flow

1. The wizard creates a job document and validates all action blocks before `Store.save_job` stores it.
2. The GUI or background heartbeat checks due jobs; `Store.claim` uses SQLite's immediate transaction to prevent concurrent claims.
3. Each isolated worker registers its PID and runs `WorkflowEngine` against the saved job actions.
4. The engine validates flow structure, executes each action, checks optional verification, and records step events and final outcome.
5. Cancellation uses per-execution local stop signals. Workers poll between actions and during cooperative delays.
6. On unexpected process loss, stale in-progress records are marked failed after a grace period; late completion cannot replace the status of a newer run.

## Trust and threat model

Workflows are user-authored automation with the signed-in account's access, not a sandbox. An imported task is disabled until reviewed. Browser and remote HTTP steps can contact specified URLs, and all native program/file/shutdown actions can have real effects. Logs and snapshots may contain private details. Repository protection therefore focuses on excluding runtime data, confidential vulnerability reporting and reviewing all commits before public release. See `SECURITY.md`.

## Known Windows limitations

Native application accessibility varies by program; UIA text/dropdown extraction may fail if the application does not expose controls. Windows desktop automation cannot operate against UAC secure desktops or locked sessions. A compiling executable does not prove that mouse coordinates, monitor DPI, focus, task scheduling or clipboard access work correctly. `WINDOWS_ACCEPTANCE.md` is the on-device certification checklist.
