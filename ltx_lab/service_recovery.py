"""Pure MuseTalk restart assessment. Deliberately contains no process controls."""
from __future__ import annotations


def assess_musetalk(before, after, *, old_pid, new_pid, launch_running, files_unchanged):
    errors = []
    if (not launch_running or not isinstance(new_pid, int) or new_pid <= 1
            or new_pid == old_pid):
        errors.append("Restart/new listener PID not confirmed")
    if not files_unchanged:
        errors.append("LaunchAgent, source or model manifest changed")
    if (before.get("ok") is not True or after.get("ok") is not True
            or before.get("device") not in {"mps", "cuda", "cpu"}
            or after.get("device") != before.get("device")
            or after.get("quality_version") != before.get("quality_version")):
        errors.append("Health/readiness/device/quality version not restored")
    if not isinstance(before.get("avatars"), list) or not isinstance(after.get("avatars"), list):
        errors.append("Avatar snapshot unavailable")
        missing = []
    else:
        missing = sorted(set(before["avatars"]) - set(after["avatars"]))
        if missing:
            errors.append("Original avatars need approved rewarm with original input media")
    return {"status": "restore_pending" if errors else "restored",
            "pending_services": ["musetalk"] if errors else [],
            "missing_avatars": missing, "errors": errors,
            "functional_inference_tested": False}
