"""Stop the Windows desktop API if its owning shell disappears."""

import ctypes
import os
import threading
from ctypes import wintypes


def monitor_desktop_parent(parent_pid: int | None) -> None:
    if parent_pid is None:
        return  # The standalone API has no desktop shell to monitor.
    if os.name != "nt":
        raise RuntimeError("Desktop parent monitoring requires Windows")
    if not 0 < parent_pid <= 0xFFFFFFFF or parent_pid == os.getpid():
        raise ValueError("Desktop parent PID must identify a separate process")

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    # Keep an actual process handle, so PID reuse cannot attach us to a new app.
    handle = kernel.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE only.
    if not handle:
        # The shell can disappear while the one-file executable is extracting.
        # Do not leave a PyInstaller unhandled-exception dialog behind either.
        os._exit(0)
    initial = kernel.WaitForSingleObject(handle, 0)
    if initial != 258:  # WAIT_TIMEOUT means the parent is still alive.
        kernel.CloseHandle(handle)
        os._exit(0 if initial == 0 else 1)

    def wait_for_shell() -> None:
        result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)  # INFINITE.
        kernel.CloseHandle(handle)
        # This worker may be serving requests or migrating a database. Once the
        # owner is gone it must not leave a background server behind. SQLite
        # handles interrupted transactions on the next open, as on any crash.
        os._exit(0 if result == 0 else 1)  # WAIT_OBJECT_0; PyInstaller then exits too.

    thread = threading.Thread(target=wait_for_shell, name="desktop-parent", daemon=True)
    try:
        thread.start()
    except Exception:
        kernel.CloseHandle(handle)
        raise
