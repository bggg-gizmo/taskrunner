# Task Runner

**Developed by the Background Gremlin Group — Creating Unique Tools for Unique Individuals.**

**Task Runner 1.2.1** — a native Windows desktop automation controller. Visual screenshot targeting, ordered workflows with nested conditions and bounded loops, cron/interval/date schedules, browser automation, HTML retrieval and parsing, file operations, per-step verification and retry, execution history, optional retro-vaporwave UI audio, and a custom application icon.

## Windows executable build

Prerequisites: Windows 10/11 x64; Python 3.11, 3.12, or 3.13 x64 installed and accessible by `py` or `python`; internet access during the first build for Python dependencies and Chromium. A Windows system is required to build the Windows executable using PyInstaller.

1. Extract the full source archive to a writable folder.
2. Double-click **`BUILD_WINDOWS.cmd`**. It checks the shared per-user Python installation, installs only missing/incompatible packages (without creating `.venv`), runs tests, checks the shared Playwright Chromium cache, builds a **fully packaged, windowed** executable, then executes a real post-build self-test against the frozen runtime and **its bundled Chromium**. The build fails if that self-test fails.
3. Open **`dist\TaskRunner\TaskRunner.exe`**. Keep the entire `dist\TaskRunner` directory together, including `_internal` and `browser-binaries`.
4. If you want scheduled jobs to run when the UI is closed, use the **Settings → Install / update scheduler** button or double-click **`INSTALL_SCHEDULER.cmd`**. It registers a Windows Task Scheduler heartbeat under the current interactive Windows account, using PowerShell's ScheduledTasks API without saving a Windows password. If Windows group policies prohibit scheduling, the app reports the registration error.
5. For source execution, use **`RUN_FROM_SOURCE.cmd`**. It also checks and installs missing runtime requirements automatically. To preinstall everything without building, run **`CHECK_DEPENDENCIES.cmd`**.

## Shared dependencies and Windows PATH

Task Runner uses **normal 64-bit Python 3.11–3.13**, preferring 3.12, then 3.11, then 3.13, instead of a per-project virtual environment. `BUILD_WINDOWS.cmd`, `RUN_FROM_SOURCE.cmd`, and `CHECK_DEPENDENCIES.cmd` all run the same preflight. The checker inspects installed distribution versions against `requirements.txt` / `requirements-build.txt`, skips installation if all versions match, and invokes `python -m pip install --user -r ...` only when something needs installing. This installs into Windows Python **user site-packages**, shared with your other Python programs using the **same Python major/minor version** and Windows user account. It does not install packages to the Task Runner folder, overwrite an existing `.venv`, or require system-wide administrator privileges.

The checker persists that Python version's user `Scripts` directory on your **user PATH**, without using `setx`, so Python-installed command-line tools are accessible from new Command Prompt windows. Python modules themselves are resolved from `site-packages`, **not** directly from PATH. Installing for Python 3.12 does not automatically install the same libraries for a separate 3.11 or 3.13 interpreter. Another program can use those modules by running under the same interpreter.

Playwright's Chromium is checked in `%LOCALAPPDATA%\ms-playwright`, its normal reusable user cache. The Windows executable additionally **bundles its own copy** of those browser binaries so the delivered application does not depend on a separately installed Python or browser cache. The EXE embeds its runtime dependencies as well; shared Python installations are for building and running source, not a requirement for end users of the EXE. Initial missing dependencies may require internet access.

If multiple Python installations are available, set `TASKRUNNER_PYTHON` to the full path of your preferred 64-bit `python.exe` before running the scripts. An activated virtual environment is deliberately rejected. Windows managed-device policy can prevent modifying user PATH; in that case `python -m <tool>` will still work, and the script reports a warning.

To remove background scheduling, use Settings → Remove scheduler or `REMOVE_SCHEDULER.cmd`. Existing saved jobs remain intact.

## Job editing

- Dashboard: Create, run, stop, edit, duplicate, enable/disable, delete, monitor jobs; export and import tasks in versioned JSON. Imported tasks are **disabled by default** until you review them.
- Wizard: Task metadata; full desktop capture; select pixel or rectangular region for click, double-click, right-click, click-then-type, or screenshot-based verification; add/edit/remove/reorder action steps. Parameter paths have Browse controls. **Validate workflow** checks saved parameters and nested flow structure without side effects; **Save + Run now** explicitly executes the full workflow.
- Supported actions: mouse clicks/moves/drags/scroll, keys/shortcuts/typing/copy/paste, create/copy/move/delete/list file operations, open/launch programs, activate/close windows, screenshot capture, variables, nested `If / Else / End if` branches, bounded `Repeat / End repeat` loops with break/continue, direct HTTP GET, Playwright Chromium navigation/click/fill/press/wait/extraction/downloads/browser close, Beautiful Soup HTML parsing, browser screenshots, shutdown and cancel-shutdown.
- Verification: Optional per-step file exists, window title, browser selector visible, or reference screenshot present. Each step can independently specify retry count, retry delay, post-action delay, and verification timeout.
- Scheduling: Manual, once, every N seconds, daily, weekly, and standard five-field cron expressions. Cron is evaluated using the local Windows timezone, including timezone database support; due timestamps are stored in UTC.
- Execution logs: Each run and individual step result are saved in SQLite, including failure details and optionally a desktop screenshot. Individual execution journals can be exported to UTF-8 text.
- Audio: Settings toggles seven **original synthesized** retro UI sound effects; sound does not control or interrupt workflow execution.

`${variable_name}` resolves an earlier variable produced by `Set variable`, `Read clipboard`, `Read text file`, `Extract browser text`, `Get browser HTML`, `Fetch HTML`, `Beautiful Soup`, `List directory`, or other actions. `Fetch HTML` records `${http_status}` and a fetched `${current_url}`. The repeat block exposes `${loop_iteration}`. Reserved variables include `${task_name}`, `${task_id}`, `${clipboard}`, `${last_file}`, `${last_screenshot}`, `${process_id}`, `${current_url}` as populated by completed steps. Unset variables raise explicit errors, avoiding silent data corruption.

## Scheduling and Windows desktop limitations

The Windows scheduled heartbeat runs once per minute **in the logged-on interactive user's session**. The GUI checks due work every second while open. The SQLite transaction claim prevents concurrent duplicate execution of the same job. **Sub-minute schedules require the GUI to remain open and running**; with the heartbeat alone, jobs are dispatched at the next one-minute check. Neither mode guarantees hard real-time timing under Windows load. The computer must be awake to execute. Overdue jobs can run after the next scheduler check, but missed recurring intervals are not replayed individually.

Automations that move the mouse, type, capture desktop pixels, or activate windows cannot operate normally on a **locked** desktop or before the user logs in. Browser jobs using headless Playwright, and purely file operations, do not have that interaction requirement but the registered heartbeat currently uses the interactive logged-on principal. Windows UAC secure desktop/elevated windows may be inaccessible to an unelevated Task Runner. Windows Task Scheduler configuration can be restricted by managed-device policies.

Visual pixel selection uses the entire virtual desktop bounding box and preserves negative monitor coordinates; Windows pointer actions use native Windows cursor input for multi-monitor targeting. If screen resolution, DPI scaling, window placement, or application appearance changes, an absolute click may need to be recaptured. Where possible, prefer Playwright selectors or window-title checks for stability.

A `Shutdown Windows` step calls the real Windows shutdown command. The wizard requests explicit confirmation on adding it and the dashboard requests confirmation before starting such workflows manually. Scheduled workflows with this step will execute according to their saved configuration, without another interactive confirmation. The default shutdown countdown is 60 seconds; run `shutdown /a` to cancel while pending.

Settings and job data are stored under `%LOCALAPPDATA%\TaskRunner`; screenshots include potentially sensitive desktop contents, so they should be protected as local files. Set `TASKRUNNER_HOME` to an alternate folder before launching if needed. **No telemetry, network account, or cloud service is required for desktop-only jobs.** Browser actions access only the websites you explicitly configure.

## Control flow, validation and safety

Use `If variable matches` followed by other steps, an optional `Else`, then `End if`. Conditions compare a saved variable with a literal or `${expanded_variable}`; supported operators include equals, not equals, contains, not contains, empty, not empty, and regex matches. Nested blocks are supported. Put `Repeat actions` before the steps to repeat and `End repeat` after them. `Break repeat loop` exits the closest repeat, while `Continue repeat loop` moves to the next iteration. Iteration counts are limited to 0–10,000 and execution is guarded by a 100,000-step safety cap. Malformed branching and unknown actions fail validation **before executing any steps**.

The **Validate workflow** button is a static configuration check, not a live rehearsal. A **Save + Run now** workflow runs actual mouse clicks, launches programs, sends browser requests, edits files, and can shut down Windows when such a step is present. Importing a workflow leaves it disabled pending inspection. `Delete file` performs an actual permanent deletion, not a move to the Recycle Bin; copy/move operations refuse an existing destination unless you explicitly enable overwrite.

## Windows package diagnostics

After PyInstaller builds the EXE, `BUILD_WINDOWS.cmd` executes `dist\TaskRunner\TaskRunner.exe --self-test --report dist\TaskRunner\windows-self-test.json`. It checks runtime module imports, icon/audio assets, cron, SQLite store and workflow execution, Playwright bundled Chromium startup, and GUI module imports. A nonzero exit code fails the build; the report describes failed checks. The frozen application is forced to use its adjacent `browser-binaries` directory so a shared Playwright cache cannot mask missing package binaries. To repeat diagnostics manually, use `TaskRunner.exe --self-test --report report.json` from Command Prompt.

**Windows-only limitations:** Native Qt windows and real mouse/keyboard automation cannot be exercised in this Linux authoring environment. The final EXE, Task Scheduler registration, per-monitor DPI targeting, and normal GUI interaction still require on-device acceptance tests. The post-build self-test checks core packaging and headless browser functionality, but does not operate your mouse, keyboard, or shutdown function.

## Repository layout

- `task_runner/gui.py` — native Qt dashboard, action setup wizard, monitor, logs, settings.
- `task_runner/capture.py` — virtual-desktop screenshot selector with exact pixel conversion.
- `task_runner/actions.py` — catalog of supported typed operations.
- `task_runner/executor.py` — ordered execution, retry, verification, Playwright, Beautiful Soup, Windows desktop/file actions.
- `task_runner/flow.py` — validated nested conditional/repeat block compiler and pre-execution schema checks.
- `task_runner/diagnostics.py` — non-destructive, packaged-Windows integration self-test with JSON report.
- `task_runner/store.py` — SQLite jobs and audit logs.
- `task_runner/scheduling.py` — timezone-aware scheduling.
- `task_runner/runner.py` — Task Scheduler heartbeat, background worker, cancellation markers.
- `task_runner/sounds.py` — configurable retro audio playback.
- `assets/` — custom multi-resolution icon, original retro interface audio.
- `tests/` — scheduling, persistence, executor and verification regression tests.
- `scripts/FIND_PYTHON.cmd` — selects a supported shared Python interpreter.
- `scripts/shared_dependencies.py` — version-aware user-site installation and user PATH setup.
- `CHECK_DEPENDENCIES.cmd` — standalone dependency/browser preflight.

## Build and validation status

As of the current source audit, **61 offline tests pass and 3 timezone/cron tests are skipped** because `croniter`/`tzlocal` cannot be installed in the offline authoring environment. The build script installs those libraries and runs the **complete suite on Windows**; the post-build self-test additionally verifies browser and asset packaging. A Windows `.exe` requires a **Windows** Python/PyInstaller build. All Windows-specific interaction and native GUI behaviors require testing on an actual Windows desktop. After building, run a harmless test job such as `Write text file → Verify file exists` before enabling scheduled desktop clicks or shutdown commands.

## Version 1.2 — expanding controls, scrolling capture and precise waits

**Timing:** Every action now supports a **Wait BEFORE action (s)** field alongside the existing **Wait after action**, retry count and retry delay. Decimals are accepted. One-second scheduling remains available using **Every N seconds → 1** when the GUI is running; the Windows Task Scheduler heartbeat is registered at one-minute intervals, so jobs due every second while the GUI is closed cannot be guaranteed to execute every second. For launch/close synchronization, use **Wait for Windows window** (appears/disappears), **Wait for file or folder** (exists/missing), or **Wait for browser element state** (visible, hidden, attached, detached). All waits are bounded and check for cancellation.

**Browser dropdowns:** **Expand browser page dropdowns** opens native `<details>` disclosures and available `aria-expanded=false` controls in a configurable subtree. The result is saved as a JSON string variable. HTML `<select>` widgets are not all left visually open—browser-native popups generally only allow one at a time—so every option label/value is collected without changing selections. Use **Select browser dropdown choice** to choose an exact label, value or index afterward.

**Desktop dropdowns:** **Inspect Windows app dropdowns** uses the Windows UI Automation ExpandCollapse pattern to expand eligible ComboBox, Button and TreeItem controls one at a time, collect choice text where exposed, and restore their original state. It cannot force custom-rendered or accessibility-inaccessible dropdowns to open. The JSON report is saved into the configured workflow variable.

**Copy all scrolling text:** **Capture entire scrolling web text** scrolls document and overflow containers incrementally, waits for lazy-loaded content, and collects unique nonempty text lines (up to your bounded number of scrolls). It can also put the result in the clipboard for later **Paste clipboard** or **Write text file** actions. For native programs, **Capture scrolling Windows app text** attempts the accessibility TextPattern document first, then uses bounded scroll and Ctrl+A/C fallback in the selected window. If the program does not expose or copy text, this action reports an error rather than silently reporting success. Text that was never rendered or exposed cannot be recovered automatically. Repeated identical lines can be deduplicated by the browser capture engine; disable nothing without user approval.

**Build reliability fix:** If the first shared `pip install --user` attempt encounters a pip wheel-cache access/permission error, the dependency checker retries automatically using `--no-cache-dir`. It does not delete or modify existing cached wheels, does not request administrator access, and still installs into the same shared user `site-packages` as before. Other installation errors are surfaced as errors.

## v1.2.1 — Fixes for actual Windows run and transient-menu capture

**Why your previous 7-click task stopped:** execution log 7 records seven cursor actions in less than one second, then a failure while typing (`LP__POINT` pointer mismatch). A successfully dispatched click was logged as successful even if the intended program did not react. These are separate problems.

**Native typing fix:** `Type text` on Windows now uses independent `SendInput` Unicode keyboard events (`task_runner/wininput.py`) instead of the PyAutoGUI cursor polling path. It does not touch the clipboard, and tolerates international text, tabs, Enter/newlines, and surrogate pairs. A private Windows cursor handle continues to isolate native pointer functions from PyAutoGUI's shared `GetCursorPos` configuration. Use an unlocked, interactive Windows desktop.

**Context-menu capture:** The wizard exposes a **Capture RIGHT-CLICK MENU in 5s** button and an adjustable **Capture delay (seconds)** field (0–30). For a Windows right-click menu: click the 5-second button, acknowledge the short reminder, wait for Task Runner to hide, right-click the intended file/folder/application, and leave the menu open until the capture occurs. The frozen screenshot is saved *before* Task Runner is shown again, so you can select the menu row in the image afterward. For a slower popup use 10–15 seconds on the editable capture-delay field, then **Capture full screen + select**. This does not artificially reopen menus during workflow playback; each menu-opening action still needs its own automation step.

**No-screenshot controls:** The task wizard contains direct shortcuts for webpage dropdown expansion, Windows dropdown inspection, complete scrolling web/program text capture, waits, and dropdown selection. Every shortcut opens the real existing action editor and saves a normal action. Browser actions require an earlier **Open browser URL** action (Playwright's own browser), not an unrelated existing Chrome window. Windows UI Automation respects the target program's accessibility support. Native ComboBoxes may only stay open one at a time, so their options are enumerated and output as JSON.

**Retry/settle defaults:** Newly added clicks have **2 retries**, **1-second retry delay**, and **1-second after-action settling delay**, instead of firing immediately. Opening programs/folders and selecting browser elements also get one second of settling time. These defaults do *not* automatically mutate previously saved jobs. For your existing seven-click job, open **Edit → Apply retry + timing settings across existing actions… → Apply to all steps**, check the resulting delays, then save. Enable *Replace existing custom settings* only when you explicitly want to overwrite existing nonzero values. Configured retries happen only when an operation throws an error or an optional verification fails; they cannot prove success on their own.

**Verify an actual click response:** Select a workflow step, use screenshot selection and choose **Verify selected action changes this screen region**. That stores a small absolute region for `Screen region changed after action` verification; a baseline is captured immediately before the action, then frames are compared for up to the step's timeout. Unchanged pixels cause a failure and retry instead of false success. A changed region only confirms screen activity; a matched window/title, file state, or browser element may be a more precise result check. Careful: retrying non-idempotent actions (e.g. submitting a payment) can duplicate effects. This feature is opt-in.

**Run focus and audio:** Settings now has **Minimize Task Runner while manually running desktop workflows** (enabled by default). Manually started mouse/keyboard jobs allow 900 ms for Windows to finish minimizing and restore Task Runner after completion, avoiding dashboard clicks. Jobs started by the scheduler are not automatically minimized by this setting. Two new original sounds (`startup.wav`, `exit.wav`) play when the GUI starts or successfully closes, controlled by the existing *Sounds* checkbox. All five earlier cues and visual styling remain unchanged.

**Actual validation:** 61 offline regression tests passed, 3 skipped due to unavailable cron/timezone packages. The new tests check mouse-step retry defaults, real workflow retry semantics, Unicode SendInput event formation, screen region verification, action shortcuts, and seven valid WAV assets. The actual Windows EXE and screen/keyboard/multimonitor interactions must still pass `BUILD_WINDOWS.cmd` and `WINDOWS_ACCEPTANCE.md` on your Windows desktop.

## Version 1.3: record, replay, observe and install

### Record a complete desktop task

In the Task Setup Wizard, click **● Record actions / Replay**. Task Runner hides for two seconds, then records global mouse clicks, drags, scroll wheel, printable typing, keyboard shortcuts and keypresses in the active Windows session. Perform the intended task normally, including the pauses required by slow-opening applications. Press **Ctrl+Shift+F12** to stop. Task Runner returns and offers to insert the recorded actions; review every step, then use the existing Save/Save + Run now functionality. Intervals between captured actions are added as `delay_before`; a change to a new titled Windows program adds a window-appears checkpoint so slow startup need not be replayed as a hard-coded wait. Recording is capped at thirty minutes.

The recorder does **not** record everything in a whole operating system: secure UAC desktops, inaccessible applications, and password-protected surfaces may not expose events. Keyboard recording can store passwords as plain workflow text. **Do not type secrets while recording.** There is no always-on recording; recording is explicitly started and stopped in the wizard.

### Watch for things to appear or change

Use **Wait for visual change** with a selected screen region or a saved reference PNG. The condition can be that the region changes, that an image appears, or that it disappears. Set the polling period and maximum timeout. For textual output use **Wait for text / code / output** and choose `window`, `browser`, `file`, or `clipboard`, then select `contains`, `absent` or `changed`. The observed text is stored in your chosen workflow variable. When a condition becomes true, the next step executes. Pixel changes can be triggered by animation; choose a small meaningful region or a stable visual/text condition rather than the entire animated desktop.

Use **Click on-screen image** for target buttons or icons whose position moves between runs. Capture a distinctive crop with the screenshot picker or supply a reference PNG. The action searches the selected region (all screens if blank) and clicks the matching location. This is preferable to absolute coordinates when a resizable program changes layout. Recorder-generated clicks also store the window name, relative coordinates and accessible automation ID when available.

### Collect text and rendered images as output appears

Place **Start live output / image capture** before the actions you want to monitor. Choose a source: desktop/screen region (PNG snapshots on change), Windows-window accessibility text, a changing text file, clipboard text, clipboard image, or an **image output folder** (copies newly completed original PNG/JPEG/WebP/BMP/GIF files). Provide a local output directory, sampling interval and a maximum number of changed captures. Later workflow steps continue while the capture worker runs. Place **Stop live output capture** after them; the output directory includes a `capture-manifest.json` with the saved filenames. Capture also terminates when a workflow completes or is cancelled.

Use **Save clipboard image** when you specifically copied a rendered image into the Windows clipboard. Use **Run process and continuously save output** to capture a program's stdout and stderr into a file as the process runs. The latter waits for the program to finish or its timeout. For browser pages, the existing **Save browser screenshot**, **Capture entire scrolling web text**, and **Get browser HTML** remain available.

### Install and uninstall

First compile with `BUILD_WINDOWS.cmd`. Run `INSTALL_WINDOWS.cmd` for a per-user application installation in `%LOCALAPPDATA%\Programs\TaskRunner` with a Start Menu entry and Installed Apps uninstall registration. To remove, use the Windows Installed Apps Task Runner entry or `UNINSTALL_WINDOWS.cmd`. It removes the app, shortcut, and TaskRunnerScheduler entry. The local data directory `%LOCALAPPDATA%\TaskRunner` remains unless you explicitly request and confirm removal. It never uninstalls shared Python packages or the shared Playwright browser cache.

---

## Task Runner 1.4: Adaptive Precision and Visual Playback Debugger

**Enable the debugger:** Select a task on Dashboard, then choose **▶ Debug replay**. Task Runner claims the run and opens Execution Logs with a live step list. The run starts paused so you can review it before any mouse/keyboard action executes. **Step once** authorizes exactly one action, including its configured delays and verification. **Continue** runs until the next failure or completion. **Pause** takes effect at the next step boundary. **Emergency stop** cancels cooperative waits and requests cancellation of the running workflow; **Ctrl+Shift+F11** works during an active Windows task when the global listener is available.

**Teach a failed click:** With a debug run paused at a click action, choose **Teach current click…**. The application hides, takes a real virtual-desktop screenshot, and opens the existing pixel/region selection dialog. Choose the button or a tight, distinctive region. The new absolute position, available window/UI Automation target and reference image are saved to the task and linked to that execution. For a failed action, explicitly choose **Retry failed step**; simply correcting a target never replays a potentially irreversible operation.

**Click certainty options:** In the step editor, a click can specify a reference PNG, minimum matching confidence, search timeout, strict verified targeting, and whether to fall back to a window-relative coordinate. With strict matching enabled, a missing or ambiguous control/image is an error, not an invitation to click the last recorded screen position. Existing v1.3 coordinate-only clicks retain their previous behavior by default.

## Observing screen text with offline OCR

Use **Wait for visible text (offline OCR)** to watch a selected desktop region and wait for text to appear, disappear or change. Set a confidence threshold, polling interval, maximum wait, and consecutive matching screenshot count. The recognized text is stored in a named variable. RapidOCR uses its locally bundled ONNX inference models; this action does not require an online OCR service. The Windows builder includes those files and the self-test verifies model initialization. Use a small, stable region rather than a full animated desktop whenever possible.

## File-trigger schedules and watcher latency

In a task's schedule editor choose **When a file or folder changes**, supply an absolute path, and choose **created**, **modified**, **removed** or **any**. The first observation establishes a baseline instead of firing unexpectedly at startup. The current GUI checks approximately once per second; the installed Windows background heartbeat checks approximately once per minute. Both use an atomic SQLite execution claim so two processes do not launch the same event simultaneously. File watches are polling-based, not native filesystem notification subscriptions.

## Output Gallery and private captures

Use **Output Gallery** in the left navigation, select the folder where the existing live-capture action writes its files, and refresh the listing. PNG/JPG and other supported images display a preview; UTF-8 text or log files show a readable excerpt. Equal-sized captures are hashed to identify real byte-identical duplicates. **Export capture bundle** creates a ZIP with a SHA-256 manifest for each included file. You choose and confirm the export, because captured screenshots and logs can contain personal or confidential information.

## Reusable task modules

Create a normal saved task containing the reusable steps. In another workflow add **Run reusable task module**, entering the saved task's numerical ID. Task Runner expands nested modules before executing any action and rejects missing jobs, cycles, excessive nesting and oversized expansions. Child actions share the invoking workflow's variables. Modules do not automatically activate their own schedules. If a sub-action needs verification or retries, configure those on the action inside the module.

## Local credential vault

Open **Settings → Local credential vault** to store or update a named secret. On Windows the secret bytes are encrypted using the signed-in user's DPAPI protection. Add **Read protected vault credential** to a task to load the value into a variable, then use normal `${variable}` interpolation where authorized. Secrets are not placed in JSON task exports or `.trpkg` bundles. If you intentionally type or write a secret to a target app, that app or output file can of course receive it. Deleting the Task Runner installation preserves the encrypted vault with the other local user data until you explicitly remove it.

## Portable `.trpkg` workflow bundles

The Dashboard's **Export package** button creates a ZIP-format `.trpkg` containing the root task, referenced saved modules and reference images. It hashes each attached file; the export dialog asks separately before bundling referenced executable scripts. **Import package** checks manifest format, path safety, archive size, module references and SHA-256 hashes before saving anything. Imported module jobs and the root job are created **disabled** with attached images copied under local workflow assets. Review target paths, scripts and side-effecting actions before enabling an imported workflow. Existing JSON import/export still works.

## Resume failed run safely

Every successful verified step saves a new checkpoint. Choose a failed or cancelled execution in **Execution Logs → Resume failed run…** and review the confirmation. Task Runner refuses continuation if the job changed, if the workflow uses unsupported branching or module expansion, or if a prior action left volatile browser, variable or capture state that cannot be safely reconstructed. It starts a **new execution** at the first unfinished step and never silently replays earlier successful steps. An action that failed might have partially changed an external program before it returned an error, so review your program's state before confirming continuation.

For actual Windows UI screenshots, execute `CAPTURE_UI_WINDOWS.cmd` from the extracted source directory. It launches the real PySide6 screens against a temporary isolated task database and saves screenshots under `ui-shots/`. This avoids misrepresenting designed mockups as real runtime captures.
