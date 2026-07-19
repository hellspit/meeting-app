"""Single-instance guard.

Global hotkeys are system-exclusive: a second instance would fail to register
them and put a duplicate overlay on screen. This blocks that on every platform.

Uses QLockFile rather than a Win32 named mutex — it's cross-platform, and it
detects stale locks left behind by a process that was killed rather than closed
(it stores the owning PID and checks whether that process still exists).
"""

from __future__ import annotations

from PySide6.QtCore import QDir, QLockFile

_LOCK_NAME = "meeting-assistant-overlay.lock"

# Module-level so the lock is held for the process lifetime. Releasing it (or
# letting it be garbage collected) would let a second instance start.
_lock: QLockFile | None = None


def acquire_single_instance() -> bool:
    """True if we got the lock; False if another instance already holds it."""
    global _lock
    if _lock is not None:
        return True
    _lock = QLockFile(f"{QDir.tempPath()}/{_LOCK_NAME}")
    # Don't treat a long-running instance as stale — only a dead PID counts.
    _lock.setStaleLockTime(0)
    if not _lock.tryLock(100):
        _lock = None
        return False
    return True


def release_single_instance() -> None:
    global _lock
    if _lock is not None:
        _lock.unlock()
        _lock = None
