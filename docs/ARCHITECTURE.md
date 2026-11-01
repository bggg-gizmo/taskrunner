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

Native application accessibility varies by program; UIA text/dropdown extraction may fail if the application does not expose controls. Windows desktop automation cannot operate against UAC secure desktops or locked sessions. A compiling executable does not prove that mouse coordinates, monitor DPI, focus, task scheduling or clipboard access work correctly. [`docs/V1.5_WINDOWS_ACCEPTANCE.md`](V1.5_WINDOWS_ACCEPTANCE.md) is the on-device certification checklist.

## 1.4 local intelligence and control-plane additions

`precision.py` ranks target candidates independent of Windows input APIs, while `winmouse.py` supplies UI Automation window/control information and requests per-monitor DPI awareness before QApplication starts. Legacy absolute coordinates remain an explicitly lower-confidence fallback. `debugger.py` coordinates pause/step/retry through `Store.debug_controls`, which is shared across GUI threads and CLI worker subprocesses. `Store.debug_corrections` links operator corrections to an execution; a correction also updates the saved job after workflow validation. `Store.debug_artifacts` tracks on-disk screenshots in the local user data directory.

`recovery.py` hashes the preflight-expanded execution plan and validates conservative checkpoint continuation restrictions. `Store.execution_checkpoints` records verified completed steps; `Store.claim_resume` creates a new execution only after explicit GUI confirmation and matching plan validation. A resumed run never assumes that an incomplete external operation was automatically rolled back.

`ocr.py` uses locally bundled RapidOCR ONNX resources. `file_events.py` supplies a stable file/folder fingerprint and transition classification; `Store.file_watch_state` persists watcher baselines, and both the GUI polling loop and the Windows scheduler heartbeat use SQLite atomic claims. `gallery.py` indexes local capture directories, hashes duplicate files and creates checksummed exports without sending data anywhere.

`vault.py` persists Windows DPAPI user-bound secret blobs under the local application data directory. No silent plaintext fallback is allowed. `modules.py` preflights reusable task expansion and recursion. `packages.py` securely imports/exports `.trpkg` archives with SHA-256 checks, asset path validation, size limits and disabled-by-default imported jobs. All new SQLite tables are created with `CREATE TABLE IF NOT EXISTS` on existing installations; previous task and execution data are preserved.
