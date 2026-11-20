"""Read window state and send a close request on a disposable Windows runner."""

import ctypes
from ctypes import wintypes

from smoke_sidecar import require


class WindowsWindow:
    def __init__(self, owner_pid: int, title: str):
        self.owner_pid = owner_pid
        self.title = title
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.PostMessageW.restype = wintypes.BOOL

    def owns(self, handle: int) -> bool:
        pid = wintypes.DWORD()
        return bool(self.user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))) and pid.value == self.owner_pid

    def find(self) -> int | None:
        matches = []

        @self.callback_type
        def collect(handle, _data):
            if self.owns(handle):
                title = ctypes.create_unicode_buffer(256)
                self.user32.GetWindowTextW(handle, title, len(title))
                if title.value == self.title:
                    matches.append(handle)
            return True

        if not self.user32.EnumWindows(collect, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        require(len(matches) <= 1, "More than one main window belongs to the desktop shell")
        return matches[0] if matches else None

    def visibility(self, handle: int) -> bool | None:
        if self.owns(handle):
            return bool(self.user32.IsWindowVisible(handle))
        return None  # An invalid or destroyed window must not count as hidden.

    def request_close(self, handle: int) -> None:
        require(self.owns(handle), "Refusing to close a window outside the tested shell")
        if not self.user32.PostMessageW(handle, 0x0010, 0, 0):  # WM_CLOSE
            raise ctypes.WinError(ctypes.get_last_error())
