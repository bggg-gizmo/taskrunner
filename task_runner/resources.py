"""Opt-in, bounded local RAM/VRAM observability for Task Runner workflows.

RAM uses psutil. Optional NVIDIA compute-process VRAM is queried through the
installed nvidia-smi executable; other GPUs return *unavailable*, not zero.
No background scanning occurs unless the user starts a workflow guard or opens
the Resource Monitor screen. Never terminate an unrelated process.
"""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Callable

_MIB = 1024 * 1024


def _psutil():
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError('Resource monitoring requires psutil. Run CHECK_DEPENDENCIES.cmd.') from exc
    return psutil


@dataclass(frozen=True)
class ResourceSample:
    pid: int
    process_ram_mb: float
    process_count: int
    available_ram_mb: float
    total_ram_mb: float
    system_used_percent: float
    process_gpu_vram_mb: float | None = None


def _nvidia_values(args: list[str], timeout=2.0) -> list[str] | None:
    """Never shell-execute a command or block a workflow indefinitely."""
    try:
        result = subprocess.run(['nvidia-smi', *args], capture_output=True, text=True,
                                errors='replace', timeout=timeout, check=False,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def nvidia_overview() -> list[dict] | None:
    """NVIDIA GPU global VRAM; not a measurement of per-program VRAM."""
    rows = _nvidia_values(['--query-gpu=name,memory.used,memory.total',
                           '--format=csv,noheader,nounits'])
    if rows is None:
        return None
    output = []
    try:
        for row in rows:
            name, used, total = [part.strip() for part in row.rsplit(',', 2)]
            output.append({'name': name, 'used_mb': float(used), 'total_mb': float(total)})
    except (ValueError, IndexError):
        return None
    return output or None


def nvidia_compute_vram(pids: set[int]) -> float | None:
    """NVIDIA CUDA/compute allocation for listed PIDs, if reported.

    A missing PID or unsupported driver is unknown, not zero; graphical and
    other GPU work may be absent from this compute-process interface.
    """
    rows = _nvidia_values(['--query-compute-apps=pid,used_gpu_memory',
                           '--format=csv,noheader,nounits'])
    if rows is None:
        return None
    entries = {}
    try:
        for row in rows:
            pid_text, value = [part.strip() for part in row.split(',', 1)]
            if value.casefold() in ('n/a', '[not supported]'):
                continue
            pid = int(pid_text)
            if pid in pids:
                entries[pid] = entries.get(pid, 0.0) + float(value)
    except (ValueError, IndexError):
        return None
    if not any(pid in entries for pid in pids):
        return None
    return sum(entries.values())


def process_identity(pid: int) -> tuple[int, float]:
    process = _psutil().Process(int(pid))
    return int(pid), float(process.create_time())


def sample_resources(pid: int = 0, include_gpu: bool = False) -> ResourceSample:
    ps = _psutil()
    ram = ps.virtual_memory()
    members = []
    if int(pid):
        root = ps.Process(int(pid))
        # A missing/inaccessible root is an error, not a zero-memory sample.
        members = [root]
        try:
            members.extend(root.children(recursive=True))
        except (ps.NoSuchProcess, ps.AccessDenied):
            pass
    rss = 0
    active_pids = set()
    for proc in members:
        try:
            info = proc.memory_info()
            rss += info.rss
            active_pids.add(proc.pid)
        except (ps.NoSuchProcess, ps.AccessDenied, ps.ZombieProcess):
            continue
    if int(pid) and not active_pids:
        raise ProcessLookupError(f'PID {pid} exited or is inaccessible')
    gpu = nvidia_compute_vram(active_pids) if include_gpu and active_pids else None
    return ResourceSample(int(pid), round(rss / _MIB, 2), len(active_pids),
                          round(ram.available / _MIB, 2), round(ram.total / _MIB, 2),
                          float(ram.percent), gpu)


def threshold_breaches(sample: ResourceSample, process_ram_limit_mb: float = 0,
                       minimum_available_ram_mb: float = 0,
                       process_gpu_vram_limit_mb: float = 0) -> tuple[str, ...]:
    hits = []
    if process_ram_limit_mb > 0 and sample.process_ram_mb >= process_ram_limit_mb:
        hits.append(f'Process tree RAM {sample.process_ram_mb:.1f} MiB ≥ {process_ram_limit_mb:.1f} MiB limit')
    if minimum_available_ram_mb > 0 and sample.available_ram_mb <= minimum_available_ram_mb:
        hits.append(f'System available RAM {sample.available_ram_mb:.1f} MiB ≤ {minimum_available_ram_mb:.1f} MiB minimum')
    if process_gpu_vram_limit_mb > 0 and sample.process_gpu_vram_mb is not None and sample.process_gpu_vram_mb >= process_gpu_vram_limit_mb:
        hits.append(f'NVIDIA compute VRAM {sample.process_gpu_vram_mb:.1f} MiB ≥ {process_gpu_vram_limit_mb:.1f} MiB limit')
    return tuple(hits)


def terminate_owned(identity: tuple[int, float], timeout: float = 3.0) -> list[int]:
    """Terminate only a root PID whose creation time still matches an owned launch.

    The caller must require explicit workflow opt-in. Process tree children are
    discovered under this verified root; unrelated system processes are never
    selected. Cannot guarantee that a process releases GPU driver allocations.
    """
    ps = _psutil()
    pid, created = identity
    root = ps.Process(pid)
    if abs(root.create_time() - created) > 0.01:
        raise RuntimeError('Owned process identity changed; refusing termination (PID reuse)')
    children = root.children(recursive=True)
    candidates = children + [root]
    identities = []
    for proc in candidates:
        try:
            identities.append((proc, proc.create_time()))
        except (ps.NoSuchProcess, ps.AccessDenied):
            continue
    stopped = []
    for proc, birth in identities:
        try:
            if abs(proc.create_time() - birth) < 0.01:
                proc.terminate()
                stopped.append(proc.pid)
        except (ps.NoSuchProcess, ps.AccessDenied):
            continue
    gone, alive = ps.wait_procs([proc for proc, _ in identities], timeout=timeout)
    for proc in alive:
        original = next((birth for item, birth in identities if item.pid == proc.pid), None)
        if original is None:
            continue
        try:
            if abs(proc.create_time() - original) < 0.01:
                proc.kill()
        except (ps.NoSuchProcess, ps.AccessDenied):
            continue
    return stopped


class MemoryWatch:
    """One opt-in workflow-scoped monitor. Default response is warning only."""

    def __init__(self, pid: int, *, process_ram_limit_mb=0,
                 minimum_available_ram_mb=0, process_gpu_vram_limit_mb=0,
                 interval=2.0, response='warn', owned_identity=None,
                 on_event: Callable[[str, str], None] | None = None,
                 sampler: Callable[..., ResourceSample] = sample_resources,
                 terminator: Callable[..., list[int]] = terminate_owned,
                 observed_identity: tuple[int, float] | None = None,
                 identity_provider: Callable[[int], tuple[int, float]] = process_identity):
        self.pid = int(pid)
        self.process_ram_limit_mb = float(process_ram_limit_mb)
        self.minimum_available_ram_mb = float(minimum_available_ram_mb)
        self.process_gpu_vram_limit_mb = float(process_gpu_vram_limit_mb)
        self.interval = float(interval)
        self.response = str(response)
        self.owned_identity = owned_identity
        self.observed_identity = observed_identity
        self.identity_provider = identity_provider
        if observed_identity is not None and observed_identity[0] != self.pid:
            raise ValueError('Observed process identity must match the monitored PID')
        if not 0.2 <= self.interval <= 60:
            raise ValueError('Monitoring interval must be 0.2–60 seconds')
        if any(value < 0 or value > 10_000_000 for value in (
                self.process_ram_limit_mb, self.minimum_available_ram_mb,
                self.process_gpu_vram_limit_mb)):
            raise ValueError('Memory thresholds must be 0–10,000,000 MiB (0 disables a threshold)')
        if self.response not in ('warn', 'cancel_workflow', 'terminate_owned'):
            raise ValueError('Unsupported memory alert response')
        if self.response == 'terminate_owned' and (self.pid <= 0 or
                owned_identity is None or owned_identity[0] != self.pid):
            raise ValueError('Termination requires a process launched by this workflow')
        self.on_event = on_event or (lambda _level, _message: None)
        self.sampler = sampler
        self.terminator = terminator
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.latest = None
        self.alert = None
        self.cancel_reason = None
        self.samples = 0
        self.peak_process_mb = 0.0
        self._last_hits = ()
        self._gpu_reported = False

    def poll_once(self):
        # Windows can recycle PIDs. Stop watching rather than attributing a
        # new, unrelated process's memory to the selected program. This check
        # applies to *all* guard policies, including warning-only monitoring.
        if self.observed_identity is not None:
            try:
                current = self.identity_provider(self.pid)
            except (ProcessLookupError, OSError) as exc:
                raise ProcessLookupError(f'Monitored PID {self.pid} is no longer available') from exc
            if (current[0] != self.observed_identity[0] or
                    abs(current[1] - self.observed_identity[1]) > 0.01):
                raise ProcessLookupError(
                    f'Monitored PID {self.pid} was reused; resource guard stopped')
        sample = self.sampler(self.pid, include_gpu=self.process_gpu_vram_limit_mb > 0)
        # stop() can be requested while a slow GPU/system sample is running.
        # Do not dispatch a new cancellation or termination after that request.
        if self._stop.is_set():
            return sample
        hits = threshold_breaches(sample, self.process_ram_limit_mb,
                                  self.minimum_available_ram_mb,
                                  self.process_gpu_vram_limit_mb)
        with self._lock:
            self.latest = sample
            self.samples += 1
            self.peak_process_mb = max(self.peak_process_mb, sample.process_ram_mb)
        if self.process_gpu_vram_limit_mb and sample.process_gpu_vram_mb is None and not self._gpu_reported:
            self.on_event('WARNING', 'NVIDIA compute-process VRAM unavailable; GPU threshold cannot be enforced')
            self._gpu_reported = True
        # Track threshold *identity*, not changing numeric readings, to avoid
        # flooding execution logs on every sample above the limit.
        hit_keys = tuple(hit.split(' ', 1)[0] for hit in hits)
        if hit_keys != self._last_hits:
            if hits:
                reason = '; '.join(hits)
                self.alert = reason
                self.on_event('WARNING', f'Memory guard PID {self.pid}: {reason}')
                if self.response == 'cancel_workflow':
                    self.cancel_reason = f'Workflow cancelled by configured memory guard: {reason}'
                    self._stop.set()
                elif self.response == 'terminate_owned':
                    try:
                        stopped = self.terminator(self.owned_identity)
                        self.on_event('WARNING', f'Operator-configured stop of owned process tree: {stopped}')
                    except Exception as exc:
                        self.on_event('ERROR', f'Owned-process termination failed: {exc}')
                    self.cancel_reason = f'Memory guard stopped the workflow: {reason}'
                    self._stop.set()
            else:
                self.alert = None
                self.on_event('INFO', f'Memory guard PID {self.pid}: thresholds recovered')
        self._last_hits = hit_keys
        return sample

    def _run(self):
        # start() takes the first sample synchronously; do not double-poll.
        while not self._stop.wait(self.interval):
            try:
                self.poll_once()
            except (ProcessLookupError, OSError) as exc:
                self.on_event('INFO', f'Memory guard stopped: {exc}')
                break
            except Exception as exc:
                self.cancel_reason = f'Memory guard failed: {type(exc).__name__}: {exc}'
                self.on_event('ERROR', self.cancel_reason)
                break
        self._stop.set()

    def start(self):
        if self._thread is not None:
            raise RuntimeError('Memory guard already started')
        # Validate the PID before returning success to the workflow.
        self.poll_once()
        if not self._stop.is_set():
            self._thread = threading.Thread(target=self._run, name='TaskRunnerMemoryWatch', daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(3.0, self.interval + 2))
        return {'pid': self.pid, 'samples': self.samples,
                'peak_process_mb': round(self.peak_process_mb, 2),
                'alert': self.alert, 'cancel_reason': self.cancel_reason}
