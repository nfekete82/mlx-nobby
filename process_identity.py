"""Content-free process identities, including subsecond birth time on macOS."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys


class _BSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "rfu")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "pjobc", "tdev", "tpgid", "nice")]
    _fields_ += [("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


def snapshot(pid):
    if sys.platform == "darwin":
        info = _BSDInfo()
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        size = lib.proc_pidinfo(int(pid), 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info):
            raise ProcessLookupError(pid)
        return {"pid": int(info.pid), "ppid": int(info.ppid), "pgid": int(info.pgid),
                "birth": f"{info.start_sec}.{info.start_usec:06d}", "zombie": info.status == 5}
    stat = (Path("/proc") / str(pid) / "stat").read_text()
    fields = stat.rsplit(")", 1)[1].split()
    return {"pid": int(pid), "ppid": int(fields[1]), "pgid": int(fields[2]),
            "birth": fields[19], "zombie": fields[0] == "Z"}


def birth(pid):
    return snapshot(pid)["birth"]


def table():
    result = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat="],
                            capture_output=True, text=True, timeout=3, check=True)
    rows = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        pid, ppid, pgid = map(int, parts[:3])
        try:
            # Birth, ancestry, group and state must come from the SAME kernel
            # snapshot. Combining an old ps row with a reused PID's new birth
            # time could otherwise incorrectly claim a foreign process.
            rows[pid] = snapshot(pid)
        except (ProcessLookupError, FileNotFoundError):
            continue
    return rows


def same(saved, current):
    return bool(current and saved.get("pid") == current.get("pid") and saved.get("birth") == current.get("birth"))
