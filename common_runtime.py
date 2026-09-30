"""Standalone OS and output helpers; no land recorder dependency."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import os
import sys

def process_path(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.OpenProcess(0x1000,False,pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if not k.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(buf.value)
    finally:
        k.CloseHandle(handle)


def percent(value):
    return '—' if value is None else f'{value:.2%}'


def atomic_text(path, text):
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(text,encoding='utf-8')
    tmp.replace(path)


def configure_tk():
    root=Path(sys.prefix)/'tcl'
    if (root/'tcl8.6/init.tcl').exists() and (root/'tk8.6/tk.tcl').exists():
        os.environ['TCL_LIBRARY']=os.path.relpath(root/'tcl8.6')
        os.environ['TK_LIBRARY']=os.path.relpath(root/'tk8.6')
