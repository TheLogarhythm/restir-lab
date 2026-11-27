"""Measure private memory and identify the existing Mogwai window."""

import ctypes as C
from ctypes import wintypes as W
from contextlib import contextmanager
import os

SW_RESTORE = 9
WM_GETMINMAXINFO = 0x0024


class MinMaxInfo(C.Structure):
    _fields_ = [(name, W.POINT) for name in ("reserved", "max_size", "max_position", "min_track", "max_track")]


def bind(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, args
    return function


def process_commit_bytes():
    """Current private committed bytes reported by Windows for this Mogwai."""
    class Counters(C.Structure):
        _fields_ = [("cb", W.DWORD), ("page_faults", W.DWORD)] + [
            (key, C.c_size_t) for key in ("peak_working_set", "working_set", "peak_paged",
             "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")
        ]
    counters = Counters()
    counters.cb = C.sizeof(counters)
    get_info = C.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    get_info.argtypes = [W.HANDLE, C.POINTER(Counters), W.DWORD]
    get_info.restype = W.BOOL
    if get_info(W.HANDLE(-1), C.byref(counters), counters.cb):
        return counters.private
    return None


class WindowIdentity:
    def __init__(self):
        user = C.PyDLL("user32", use_last_error=True)
        iptr = C.c_ssize_t
        enum_proc = C.WINFUNCTYPE(W.BOOL, W.HWND, iptr)
        enum = bind(user, "EnumWindows", W.BOOL, enum_proc, iptr)
        owner = bind(user, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
        class_name = bind(user, "GetClassNameW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
        self.visible = bind(user, "IsWindowVisible", W.BOOL, W.HWND)
        matches = []

        @enum_proc
        def visit(hwnd, data):
            pid = W.DWORD()
            owner(hwnd, C.byref(pid))
            if pid.value == os.getpid():
                name = C.create_unicode_buffer(96)
                class_name(hwnd, name, len(name))
                if name.value.startswith("GLFW") and self.visible(hwnd):
                    matches.append(hwnd)
            return True

        enum(visit, 0)
        if len(matches) != 1:
            raise RuntimeError(f"Expected one visible Mogwai window, found {matches}")
        self.hwnd = matches[0]
        self.title = bind(user, "SetWindowTextW", W.BOOL, W.HWND, W.LPCWSTR)
        self.get_client_rect = bind(user, "GetClientRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
        self.get_window_rect = bind(user, "GetWindowRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
        self.is_zoomed = bind(user, "IsZoomed", W.BOOL, W.HWND)
        self.show_window = bind(user, "ShowWindow", W.BOOL, W.HWND, C.c_int)

    def rect_size(self, get_rect):
        rect = W.RECT()
        if not get_rect(self.hwnd, C.byref(rect)):
            raise C.WinError(C.get_last_error())
        return rect.right - rect.left, rect.bottom - rect.top

    def client_size(self):
        return self.rect_size(self.get_client_rect)

    @contextmanager
    def allow_outer_size(self, width, height):
        controls = C.WinDLL("comctl32", use_last_error=True)
        iptr, uptr = C.c_ssize_t, C.c_size_t
        procedure = C.WINFUNCTYPE(iptr, W.HWND, W.UINT, uptr, iptr, uptr, uptr)
        default = bind(controls, "DefSubclassProc", iptr, W.HWND, W.UINT, uptr, iptr)
        install = bind(controls, "SetWindowSubclass", W.BOOL, W.HWND, procedure, uptr, uptr)
        remove = bind(controls, "RemoveWindowSubclass", W.BOOL, W.HWND, procedure, uptr)

        @procedure
        def resize_limits(hwnd, message, wparam, lparam, subclass_id, data):
            result = default(hwnd, message, wparam, lparam)
            if message == WM_GETMINMAXINFO and lparam:
                limits = MinMaxInfo.from_address(lparam)
                for point in (limits.max_size, limits.max_track):
                    point.x = max(point.x, width)
                    point.y = max(point.y, height)
            return result

        if not install(self.hwnd, resize_limits, 0, 0):
            raise RuntimeError("Could not install the temporary Mogwai resize callback")
        try:
            yield
        finally:
            if not remove(self.hwnd, resize_limits, 0):
                raise RuntimeError("Could not remove the temporary Mogwai resize callback")

    def resize_client(self, resize_framebuffer, flush_events, width, height):
        requested = (width, height)
        if self.client_size() == requested:
            return requested
        if self.is_zoomed(self.hwnd):
            self.show_window(self.hwnd, SW_RESTORE)
        resize_framebuffer(*requested)
        flush_events()
        current_width, current_height = self.client_size()
        if (current_width, current_height) == requested:
            return requested

        # The normal resize can clamp the decorated outer rectangle to the screen.
        # Raise this window's maximum outer size only while resizing it.
        outer_width, outer_height = self.rect_size(self.get_window_rect)
        with self.allow_outer_size(width + outer_width - current_width, height + outer_height - current_height):
            resize_framebuffer(*requested)
            flush_events()
        return self.client_size()
