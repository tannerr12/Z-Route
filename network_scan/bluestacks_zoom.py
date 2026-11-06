"""Zoom the focused BlueStacks App Player using its configured Ctrl+- game control.

No Ollama or additional Python dependency. Win32 keyboard input is delivered
ONLY after verifying a visible BlueStacks App Player window has foreground.
BlueStacks' Zoom game control must be enabled and configured for Ctrl+-.
"""
from __future__ import annotations

import sys
import time


def bluestacks_foreground_handle():
    """Return the specific visible BlueStacks game window, or fail closed."""
    if sys.platform != "win32":
        raise RuntimeError("BlueStacks keyboard zoom requires Windows")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    titles = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        size = user32.GetWindowTextLengthW(hwnd)
        if size <= 0:
            return True
        buf = ctypes.create_unicode_buffer(size + 1)
        user32.GetWindowTextW(hwnd, buf, len(buf))
        name = buf.value
        if "bluestacks app player" in name.casefold():
            titles.append((hwnd, name))
        return True

    if not user32.EnumWindows(callback_type(visit), 0):
        raise RuntimeError("Unable to enumerate BlueStacks windows")
    if len(titles) != 1:
        raise RuntimeError(f"Expected exactly one BlueStacks App Player window, "
                           f"found {len(titles)}. Close duplicates before keyboard zoom.")
    hwnd, name = titles[0]
    if not user32.SetForegroundWindow(hwnd):
        raise RuntimeError("Windows refused to focus BlueStacks; no keys sent. "
                           "Click BlueStacks manually, then retry.")
    time.sleep(0.15)
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError("BlueStacks did not become foreground; no keys sent")
    return user32, hwnd, name


def zoom_out_ctrl_minus(hold_seconds=2.0):
    """Send one uninterrupted Ctrl+- zoom-out hold to focused BlueStacks.

    Hold continuously for the calibrated 2-5s, rather than repeating
    discrete presses (which can reset zoom in the user's BlueStacks).
    Key-up is unconditional even if a problem occurs during the hold.
    """
    if isinstance(hold_seconds,bool) or not isinstance(hold_seconds,(int,float)) or not 2.0<=hold_seconds<=5.0:
        raise ValueError('Zoom hold must be between 2.0 and 5.0 seconds')
    user32, hwnd, title = bluestacks_foreground_handle()
    import ctypes
    from ctypes import wintypes
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.keybd_event.argtypes = [
        ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]
    user32.keybd_event.restype = None

    ctrl = 0x11  # VK_CONTROL
    minus = 0xBD  # VK_OEM_MINUS (physical -/_ key)
    keyup = 0x0002
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError("BlueStacks lost focus; no zoom keys sent")
    print(f"[zoom] Holding Ctrl+- for {hold_seconds:.2f}s in foreground window: {title}", flush=True)
    user32.keybd_event(ctrl, 0, 0, None)
    try:
        time.sleep(.06)
        user32.keybd_event(minus, 0, 0, None)
        try:
            time.sleep(hold_seconds)
        finally:
            user32.keybd_event(minus, 0, keyup, None)
    finally:
        user32.keybd_event(ctrl, 0, keyup, None)
