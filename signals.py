"""Read idle age and optional foreground metadata, never keystrokes/content."""
import ctypes
from ctypes import wintypes
import ctypes.util
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import time


@dataclass
class Sample:
    at: float
    idle: float | None = None
    context: str = ''
    fullscreen: bool = False
    own: bool = False


class WindowsSignals:
    description = 'Windows · inatividade e janela em foco disponíveis'
    idle_available = True
    context_available = True

    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user.MonitorFromWindow.restype = wintypes.HANDLE
        self.user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

    def sample(self, mode):
        class LastInput(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]
        info = LastInput(ctypes.sizeof(LastInput), 0)
        idle = None
        if self.user.GetLastInputInfo(ctypes.byref(info)):
            idle = ((self.kernel.GetTickCount() & 0xffffffff) - info.dwTime) & 0xffffffff
            idle /= 1000
        sample = Sample(time.time(), idle)
        hwnd = self.user.GetForegroundWindow()
        if not hwnd:
            return sample
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        sample.own = pid.value == os.getpid()
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]
        monitor = self.user.MonitorFromWindow(hwnd, 2)
        mi, rect = MonitorInfo(), wintypes.RECT()
        mi.cbSize = ctypes.sizeof(mi)
        if self.user.GetClientRect(hwnd, ctypes.byref(rect)) and self.user.GetMonitorInfoW(monitor, ctypes.byref(mi)):
            left, right = wintypes.POINT(rect.left, rect.top), wintypes.POINT(rect.right, rect.bottom)
            if self.user.ClientToScreen(hwnd, ctypes.byref(left)) and self.user.ClientToScreen(hwnd, ctypes.byref(right)):
                sample.fullscreen = left.x <= mi.rcMonitor.left and left.y <= mi.rcMonitor.top and right.x >= mi.rcMonitor.right and right.y >= mi.rcMonitor.bottom
        if mode == 'idle':
            return sample
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        app = ''
        if handle:
            try:
                text = ctypes.create_unicode_buffer(4096)
                length = wintypes.DWORD(len(text))
                if self.kernel.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(length)):
                    app = Path(text.value).name
            finally:
                self.kernel.CloseHandle(handle)
        sample.context = app
        return sample


class ManualSignals:
    description = 'Modo manual · detecção automática indisponível nesta sessão'
    idle_available = False
    context_available = False

    def sample(self, mode):
        return Sample(time.time())


class X11Signals:
    description = 'Linux X11 · inatividade e janela em foco disponíveis'
    idle_available = True
    context_available = True

    def __init__(self):
        self.x = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        self.ss = ctypes.CDLL(ctypes.util.find_library('Xss') or 'libXss.so.1')
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise OSError('Sem sessão X11')
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.root = self.x.XDefaultRootWindow(self.display)
        self.x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.x.XInternAtom.restype = ctypes.c_ulong
        self.x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
        self.x.XFree.argtypes = [ctypes.c_void_p]
        # Foreground windows can disappear between reads. Ignore X11 BadWindow
        # rather than letting Xlib's default error handler terminate the app.
        self.error_handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda display, error: 0)
        self.x.XSetErrorHandler.argtypes = [type(self.error_handler)]
        self.x.XSetErrorHandler(self.error_handler)
        class SaverInfo(ctypes.Structure):
            _fields_ = [('window', ctypes.c_ulong), ('state', ctypes.c_int), ('kind', ctypes.c_int), ('since', ctypes.c_ulong), ('idle', ctypes.c_ulong), ('eventMask', ctypes.c_ulong)]
        self.info = SaverInfo()
        self.ss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]

    def property(self, window, name):
        atom = self.x.XInternAtom(self.display, name.encode(), 1)
        if not atom:
            return None
        actual, fmt, count, remaining, pointer = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        status = self.x.XGetWindowProperty(self.display, window, atom, 0, 1024, 0, 0, ctypes.byref(actual), ctypes.byref(fmt), ctypes.byref(count), ctypes.byref(remaining), ctypes.byref(pointer))
        if status != 0 or not pointer:
            return None
        try:
            if fmt.value == 32:
                return list(ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ulong))[:count.value])
            return ctypes.string_at(pointer, count.value).decode('utf-8', errors='replace')
        finally:
            self.x.XFree(pointer)

    def sample(self, mode):
        idle = self.info.idle / 1000 if self.ss.XScreenSaverQueryInfo(self.display, self.root, ctypes.byref(self.info)) else None
        sample = Sample(time.time(), idle)
        window = self.property(self.root, '_NET_ACTIVE_WINDOW')
        if not window:
            return sample
        window = window[0]
        pid = self.property(window, '_NET_WM_PID')
        sample.own = bool(pid and pid[0] == os.getpid())
        states = self.property(window, '_NET_WM_STATE') or []
        fullscreen = self.x.XInternAtom(self.display, b'_NET_WM_STATE_FULLSCREEN', 1)
        sample.fullscreen = fullscreen in states
        if mode != 'idle':
            app = self.property(window, 'WM_CLASS') or ''
            app = app.replace('\x00', ' ').strip() if isinstance(app, str) else ''
            sample.context = app
        return sample


def make_signals():
    try:
        if sys.platform == 'win32':
            return WindowsSignals()
        if sys.platform.startswith('linux') and not os.environ.get('WAYLAND_DISPLAY') and os.environ.get('DISPLAY'):
            return X11Signals()
    except (OSError, AttributeError):
        pass
    fallback = ManualSignals()
    if os.environ.get('WAYLAND_DISPLAY'):
        fallback.description = 'Linux Wayland · registro manual; o sistema restringe a leitura global de inatividade e janelas'
    return fallback
