"""Local-first playback debugging, step artifacts, and operator-controlled correction.

All commands live in SQLite so a GUI and a separate scheduled worker can
coordinate without sharing memory. Nothing is sent to an external service.
"""
from __future__ import annotations
import time
from pathlib import Path
from .paths import data_root


class DebugAbort(Exception):
    """Raised when the operator cancels an active debugger session."""


class PlaybackDebugger:
    def __init__(self, store, execution_id: int, should_stop=None, sleep=None):
        self.store = store
        self.execution_id = int(execution_id)
        self.should_stop = should_stop or (lambda: False)
        self.sleep = sleep or time.sleep
        self._single_step = False

    def _check_stop(self):
        if self.should_stop():
            raise DebugAbort('Playback stopped by operator')

    def _poll(self):
        self._check_stop()
        self.sleep(0.15)
        self._check_stop()

    def before(self, step_number: int):
        """Run, pause, or permit exactly one step; recheck the SQLite mode."""
        state = self.store.debug_status(self.execution_id)
        if not state or not state['enabled']:
            return
        self.store.debug_state(self.execution_id, 'pending', step_number, '')
        while True:
            self._check_stop()
            state = self.store.debug_status(self.execution_id)
            if state is None:
                return
            mode = state['mode']
            if mode == 'cancel':
                raise DebugAbort('Playback stopped by operator')
            if mode == 'run':
                self._single_step = False
                break
            if mode == 'step':
                # Consume the step request transactionally to avoid running twice
                # if a GUI refresh happens while the step executes.
                if self.store.debug_consume_step(self.execution_id):
                    self._single_step = True
                    break
            self.store.debug_state(self.execution_id, 'paused', step_number, '')
            self._poll()
        self.store.debug_state(self.execution_id, 'executing', step_number, '')

    def completed(self, step_number: int):
        state = self.store.debug_status(self.execution_id)
        if state and state['enabled']:
            self.store.debug_state(self.execution_id, 'completed_step', step_number, '')
            # mode becomes pause at step consumption time; the worker returns
            # to before() on the next step and waits.

    def failed(self, step_number: int, error: BaseException) -> bool:
        """Hold for correction only when explicitly enabled; retry only on command.

        Returning True means the caller should retry the *same* step. The
        debugger itself never replays potentially irreversible actions.
        """
        state = self.store.debug_status(self.execution_id)
        if not state or not state['enabled'] or not state['break_on_failure']:
            return False
        self.store.debug_state(self.execution_id, 'failed_paused', step_number, f'{type(error).__name__}: {error}')
        self.store.debug_command(self.execution_id, 'pause')
        while True:
            self._check_stop()
            status = self.store.debug_status(self.execution_id)
            if not status:
                return False
            if status['mode'] == 'cancel':
                raise DebugAbort('Playback stopped by operator')
            if status['mode'] == 'retry':
                if self.store.debug_consume_retry(self.execution_id):
                    self.store.debug_state(self.execution_id, 'retrying', step_number, '')
                    return True
            self._poll()

    def capture(self, step_number: int, phase: str):
        status = self.store.debug_status(self.execution_id)
        if not status or not status['enabled'] or not status['snapshots']:
            return None
        folder = data_root() / 'debug-runs' / f'run-{self.execution_id}'
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / f'step-{step_number:04d}-{phase}.png'
        try:
            import mss
            from mss.tools import to_png
            with mss.mss() as device:
                shot = device.grab(device.monitors[0])
                to_png(shot.rgb, shot.size, output=str(file))
            self.store.debug_artifact(self.execution_id, step_number, phase, str(file))
            return file
        except Exception as exc:
            # A screenshot failure must never accidentally rerun a side-effecting step.
            self.store.event(self.execution_id, 'WARNING', f'Debug screenshot unavailable: {exc}', step_number)
            return None
