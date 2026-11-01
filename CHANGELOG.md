# Task Runner Changelog

All notable public-facing changes are documented here. Archived source versions are available in [`old builds/`](old%20builds/). Source-only release status is distinguished from completed Windows acceptance testing.

## v1.5.1 — Windows runtime responsiveness and GUI editor correction

- Move GUI scheduler polls off the Qt event loop, avoid background dashboard table rebuilds during modal editors, and reduce repeated SQLite WAL journal contention.
- Keep New Task / Edit visible within the usable monitor bounds; surface errors from those dialogs and log uncaught Windows GUI callbacks to `runtime-errors.log`.
- Remove aggressive all-submodule OCR/ONNX package collection in the Windows build while preserving the ONNX runtime, local OCR models and all existing automation actions.
- Expand packaged and source Qt checks to drive actual New Task / Edit interactions and verify task persistence.

## v1.5.1 — Resource guard safety and release quality (source hotfix)

- Windows build follow-up: explicitly close SQLite backup handles before replacing the staged file; read UTF-8 schema/README in regression checks; exercise the native Windows image-click test path without changing runtime mouse handling. Windows build acceptance remains pending.
- Fixed a resource-watch PID reuse edge case: all watch policies now bind to the selected process's creation identity and stop watching if Windows recycles its PID.
- Fixed a watcher-stop race: a late threshold alert is not silently cleared when the workflow stops its guard, and a monitor already being stopped will not initiate a new termination after a slow sample completes.
- Improved per-user Windows upgrade rollback: the previous installed application is retained until the updated shortcuts and Installed Apps registration succeed.
- Refreshed README release badges, v1.5.x feature guidance, Windows user guide, build/version metadata, and regression acceptance requirements.
- Preserved all existing UI layouts, workflow action types, vault, scheduler, media assets, and v1.2.1/v1.3.0/v1.4.0 archived sources.
- Linux regression suite passed. Native Windows installation, process control, graphics driver integration and EXE self-test require on-device acceptance.

## v1.5.0 — Resource Monitor & OOM safeguards (source release)

- Introduced a read-only Resource Monitor page with live system RAM and process tree memory usage.
- Added local NVIDIA GPU VRAM statistics where supported, distinguishing global GPU use from compute-process allocations and explicitly reporting unavailable values.
- Added three opt-in workflow actions: memory snapshot, start memory guard, and stop memory guard, including captured metrics in workflow variables.
- Added configurable RAM/VRAM thresholds with warning-only default, operator-selected workflow cancellation, and optional termination restricted to a process launched within the same workflow after PID identity verification.
- Resource monitors stop and emit a peak RAM summary when workflows end; threshold fluctuations are deduplicated in logs.
- Added psutil to the shared-Python dependency and Windows runtime checks; retained all previous features and older public source archives.
- Source regression tests and privacy audit run locally. Native Windows/PyInstaller/GPU acceptance is still outstanding.

## v1.4.0 — Windows Python 3.13 OCR build fix

- Corrected the OCR dependency for Python 3.13: replaced the legacy `rapidocr-onnxruntime` constraint with the maintained `rapidocr` and the separately installed `onnxruntime` inference engine.
- Adapted the OCR result reader to the current RapidOCR `txts`/`scores` API while preserving legacy injected OCR test adapters.
- Updated PyInstaller to bundle the maintained OCR module, ONNX engine and local models; packaged self-test performs an OCR inference to detect missing model assets.
- Preserved all workflows, user data, automation features, visuals, build scripts and archived releases.

## v1.4.0 — Adaptive replay, local intelligence and recovery (source release)

- Added integrated **Visual Playback Debugger** with pause, resume, single-step, failed-step retry, per-step captures and teach-by-correction.
- Added **Adaptive Precision Engine**: UIA IDs and names, image matching, ambiguity detection, DPI-aware clicks, strict target validation and window-relative fallback.
- Added local **offline OCR** text conditions with stability frames and recorded variables; ONNX models must be bundled into the Windows EXE.
- Added **Output Gallery** with image/text previews, duplicate detection and SHA-256 verified exports.
- Added operator-approved **checkpoint continuation** with workflow checksum and safety checks; no silent rerun of irreversible actions.
- Added **reusable task modules** with cycle detection, preflight validation and shared workflow variables.
- Added **file/folder event schedules** with durable baselines and atomic claim checks.
- Added **Windows DPAPI credential vault** with explicit create/delete controls and runtime secret-variable actions.
- Added **portable workflow packages** with referenced images/modules, optional scripts, tamper detection, path checks, limits and disabled-on-import safety.
- Added run-scoped **Ctrl+Shift+F11 emergency stop** while retaining Ctrl+Shift+F12 for recording termination.
- Preserved original Qt/vaporwave UI elements, all seven sounds, prior actions, scheduling modes, build scripts, installer and uninstaller.
- Archived the complete public v1.3.0 source in [`old builds/v1.3.0/`](old%20builds/v1.3.0/). Windows acceptance remains required.

## v1.3.0 — Record, observe, capture, replay (source release)

- **Record & replay:** Record real desktop mouse clicks, dragging, scrolling, text and shortcut key events, and the actual time between actions. Review/edit the timeline before saving. Stop capture with `Ctrl+Shift+F12`.
- **Slow application startup:** Record a named-window appearance checkpoint and configure event-driven waits instead of relying solely on fixed sleeps.
- **Visual triggers:** Wait for screen changes or the appearance/disappearance of reference images. Match an image at its current desktop location before clicking.
- **Output triggers:** Wait for content in Windows windows, browser elements, clipboard, or files, then branch/continue and store the result in workflow variables.
- **Live capture:** Capture evolving screen images, clipboard images, window text, files, and completed images in an output directory; save a manifest.
- **Program output:** Stream subprocess standard output and errors to a file as the process runs.
- **More resilient clicking:** Preserve recorded absolute and window-relative positions, with accessibility identifiers when available.
- **Windows installation:** Added per-user `INSTALL_WINDOWS.cmd`, Start Menu and Installed Apps registration.
- **Proper uninstall:** Added `UNINSTALL_WINDOWS.cmd`, removing the app and its own scheduler task, retaining user data unless its deletion is explicitly confirmed.
- **Preservation:** Previous automation actions, existing wizard/editor interface, local scheduler, database, custom app icon, and seven original sounds remain supported.
- **Validation:** Source tests passed locally. Windows GUI integration, global input hooks, EXE, and installer/uninstaller require fresh native Windows acceptance testing before distributing a verified binary.

## v1.2.1 — Reliability and public release baseline

- Corrected Unicode keyboard injection on Windows, isolated native input from PyAutoGUI cursor handling.
- Delayed screenshot capture of context menus and transient controls.
- Added direct wizard shortcuts for dropdowns, scrolling text, and wait actions.
- Added optional screen-change verification, configurable retries and settling time, plus bulk timing adjustments for existing workflows.
- Added optional automatic window minimizing during manual desktop execution and the startup/exit sound cues.
- Made local file replacement safer through staged writes and copies.
- Added SQLite live backup support and prevented late workers from overwriting newer execution status.
- Added portable JSON workflow schema and improved JSON export compatibility.
- Added public security, contribution, and license documentation.
- **Archived complete source:** [`old builds/v1.2.1/`](old%20builds/v1.2.1/).

## v1.2.0 — Expanded automation controls

- Expanded browser and Windows dropdown inspection and selection.
- Added scrolling text capture, extra waits, retry/timing controls and output collection.
- Improved Windows shared-Python dependency installation when pip's wheel cache is inaccessible.
- Added Background Gremlin Group Windows executable version metadata.

## Initial Task Runner release

- Windows PySide6 task dashboard and visual screenshot-driven wizard.
- Ordered desktop automation, Playwright browser actions, Beautiful Soup extraction, clipboard/file operations, and conditional flows.
- SQLite task storage, execution logging, import/export, scheduling, original vaporwave visual assets, and selectable retro sound effects.
