"""Opt-in soft-unload transaction. No service stops, settings writes or MLX imports."""
from __future__ import annotations

import hashlib
import json
import math
import signal
from contextlib import contextmanager
from pathlib import Path

from .services import URLS, api
from .telemetry import preflight, write_json
from .offline import inspect_model, inspect_cache
from .exclusive import private_json

HEALTH_KEYS = ("loaded_model", "loaded_adapter", "loaded_models", "loaded_context_size",
               "configured_context_limit", "effective_context_limit", "loaded_tool_parser",
               "continuous_batching_enabled", "apc_enabled")


def signature(health):
    if any(key not in health for key in HEALTH_KEYS):
        raise RuntimeError("Incomplete model/configuration snapshot")
    return {key: health[key] for key in HEALTH_KEYS}


def local_identity(model):
    """Only original absolute local paths; never substitute a hub ID or resolve a revision."""
    path = Path(model)
    if not path.is_absolute() or not path.is_dir():
        raise RuntimeError("Restore requires the original absolute local model path; hub IDs unsupported")
    config = path / "config.json"
    weights = sorted(path.glob("*.safetensors"))
    if not config.is_file() or not weights:
        raise RuntimeError("Local restore weights/config missing")
    index = path / "model.safetensors.index.json"
    if index.exists():
        shards = set(json.loads(index.read_text())["weight_map"].values())
        if not shards or any(Path(s).name != s or not (path / s).is_file() for s in shards):
            raise RuntimeError("Incomplete local restore shards")
    # No expensive reads of weights. Record local file identity and config content.
    return {"path": str(path.resolve()), "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "weights": [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in weights],
            "assets": inspect_model(path)}


@contextmanager
def termination_cleanup():
    """SIGTERM unwinds finally just like Ctrl-C; SIGKILL requires journal recovery."""
    previous = signal.getsignal(signal.SIGTERM)
    def interrupt(signum, frame):
        raise KeyboardInterrupt("Lab controller received SIGTERM")
    signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


class ModelSession:
    def __init__(self, journal, targets, *, approved=False, exclusive=False,
                 restore_inference=False, minimum=20, read=api, probe=preflight):
        if not approved or not exclusive or not restore_inference:
            raise ValueError("Managed mode requires --approve-soft-unload, --confirm-exclusive-access "
                             "and --approve-restore-inference")
        if not targets or set(targets) - set(URLS):
            raise ValueError("Explicit --unload-services chat and/or router required")
        self.path, self.targets = Path(journal), list(dict.fromkeys(targets))
        self.minimum, self.read, self.probe = minimum, read, probe
        self.setting_dependencies = {}
        self.data = {"schema_version": 1, "status": "preparing", "models": {},
                     "pending_restore": [], "events": [], "child_may_be_alive": False}

    def save(self):
        private_json(self.path, self.data)

    def asset_identity(self, name, model):
        if Path(model).is_absolute():
            return local_identity(model)
        proof = self.data.get("admission_proof", {}).get(name, {})
        if proof.get("offline") is not True or not proof.get("hub_cache"):
            raise RuntimeError("Hub ID restore requires verified offline server/cache deployment")
        cache = inspect_cache(model, proof["hub_cache"])
        revision = cache["refs"].get("main")
        snapshot = cache["snapshots"].get(revision, {})
        if not snapshot.get("offline_assets_complete"):
            raise RuntimeError("Original hub ID has no complete offline main snapshot")
        if proof.get("model_resolutions", {}).get(model) != [snapshot["path"]]:
            raise RuntimeError("Actual loaded hub revision not proven or differs from offline main snapshot")
        return dict(local_identity(snapshot["path"]), repo=model, revision=revision)

    def observation(self):
        result = self.probe(self.minimum)
        if not result.get("process_visibility"):
            raise RuntimeError("Process visibility unavailable")
        snap = result.get("snapshot", {})
        values = [snap.get("swap_used_bytes"), snap.get("available_estimate_bytes")]
        if snap.get("memory_pressure_level") != 1 or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and v >= 0 for v in values):
            raise RuntimeError("System telemetry incomplete or memory pressure not normal")
        return result

    def row(self, report, name):
        rows = [r for r in report["runtimes"] if r["name"] == name]
        if len(rows) != 1:
            raise RuntimeError(f"Ambiguous/missing server: {name}")
        return rows[0]

    def settings(self, name):
        settings = self.read("GET", URLS[name] + "/v1/settings")
        if not settings.get("fingerprint"):
            raise RuntimeError("Settings fingerprint unavailable")
        current = settings.get("current")
        if not isinstance(current, dict) or "spec_draft_model" not in current:
            raise RuntimeError("Speculative model configuration unavailable")
        self.setting_dependencies[name] = current["spec_draft_model"]
        return settings["fingerprint"]

    def same_server(self, report, name):
        row = self.row(report, name)
        old = self.data["models"][name]
        if row["pid"] != old["pid"] or self.settings(name) != old["settings"]:
            raise RuntimeError(f"Server identity/settings changed: {name}")
        return row

    def prepare(self):
        report = self.observation()
        self.data["before"] = report
        # No action on unknown runtimes, active work, or unselected loaded models.
        for row in report["runtimes"]:
            if row["state"] != "unloaded_idle" and not (
                    row["name"] in self.targets and row["state"] == "loaded_idle"):
                raise RuntimeError(f"Unsafe runtime before unload: {row['name']} ({row['state']})")
        for name in self.targets:
            row = self.row(report, name)
            health = signature(row["health"])
            old = {"pid": row["pid"], "health": health, "settings": self.settings(name)}
            if row["state"] == "loaded_idle":
                if row.get("startup_dependencies") or self.setting_dependencies.get(name):
                    raise RuntimeError("Additional draft/speculative model dependencies have no verified restore contract")
                model = health["loaded_model"]
                expected = {"text_generation": {"model": model, "adapter": None,
                                                 "model_kind": "text_generation"}}
                if health["loaded_adapter"] is not None or health["loaded_models"] != expected:
                    raise RuntimeError("Only a single text model without adapters has a verified restore contract")
                old["local_identity"] = self.asset_identity(name, model)
                schema = self.read("GET", URLS[name] + "/openapi.json")
                if not all("post" in schema.get("paths", {}).get(route, {})
                           for route in ("/unload", "/chat/completions")):
                    raise RuntimeError("Documented unload/chat restore API missing")
            self.data["models"][name] = old
        self.data["status"] = "prepared"
        self.save()

    def assert_idle_configuration(self, report, *, restoring=False):
        if not report.get("process_visibility"):
            raise RuntimeError("Process visibility unavailable")
        for row in report["runtimes"]:
            if row["state"] == "unloaded_idle":
                continue
            old = self.data["models"].get(row["name"])
            if (restoring and old and row["state"] == "loaded_idle"
                    and row["pid"] == old["pid"] and signature(row["health"]) == old["health"]):
                continue
            raise RuntimeError(f"Unsafe runtime: {row['name']} ({row['state']})")

    def unload(self):
        for name, old in self.data["models"].items():
            if not old["health"]["loaded_model"]:
                continue
            report = self.observation()
            # Recheck ALL selected models, not just the next unload target.
            self.assert_idle_configuration(report, restoring=True)
            row = self.same_server(report, name)
            if row["state"] != "loaded_idle" or signature(row["health"]) != old["health"]:
                raise RuntimeError("Model changed before unload")
            self.data["pending_restore"].append(name)
            self.data["status"] = "unloading"
            self.save()  # POST can succeed even when its HTTP response times out.
            response = self.read("POST", URLS[name] + "/unload", {})
            if response.get("status") not in {"success", "no_model_loaded"}:
                raise RuntimeError("Unload response not confirmed")
            if self.same_server(self.observation(), name)["state"] != "unloaded_idle":
                raise RuntimeError("Unload did not produce an empty, idle server")
        report = self.observation()
        self.assert_idle_configuration(report)
        if not report["allowed"]:
            raise RuntimeError(f"Post-unload resource admission refused: {report['reasons']}")
        self.data.update(status="benchmark_ready", after_unload=report)
        self.save()

    def restore(self):
        errors = []
        if self.data["child_may_be_alive"]:
            self.data.update(status="restore_pending", restore_errors=["Lab child termination unconfirmed"])
            self.save()
            raise RuntimeError("Restore deferred: lab child may still hold GPU memory")
        for name in list(reversed(self.data["pending_restore"])):
            try:
                report = self.observation()
                self.assert_idle_configuration(report, restoring=True)
                row = self.same_server(report, name)
                old = self.data["models"][name]
                if row["state"] == "unloaded_idle":
                    snap = report["snapshot"]
                    if (snap.get("memory_pressure_level") != 1 or snap.get("swap_used_bytes") is None
                            or snap.get("available_estimate_bytes", 0) < self.minimum * 1024**3):
                        raise RuntimeError("Insufficient safe resources for restore")
                    # JSON normalizes tuples to lists across journal recovery.
                    identity = json.loads(json.dumps(self.asset_identity(name, old["health"]["loaded_model"])))
                    if identity != json.loads(json.dumps(old["local_identity"])):
                        raise RuntimeError("Local restore model files changed")
                    response = self.read("POST", URLS[name] + "/chat/completions", {
                        "model": old["health"]["loaded_model"], "stream": False,
                        "messages": [{"role": "user", "content": "Reply OK."}],
                        "max_tokens": 1, "temperature": 0}, timeout=120)
                    if not response.get("choices"):
                        raise RuntimeError("Restore inference not confirmed")
                    row = self.same_server(self.observation(), name)
                if row["state"] != "loaded_idle" or signature(row["health"]) != old["health"]:
                    raise RuntimeError("Restored model/configuration differs")
                self.data["pending_restore"].remove(name)
                self.save()
            except BaseException as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                break  # Do not compound an uncertain state by loading another model.
        if not errors:
            try:
                report = self.observation()
                self.assert_idle_configuration(report, restoring=True)
                for name, old in self.data["models"].items():
                    if signature(self.same_server(report, name)["health"]) != old["health"]:
                        raise RuntimeError(f"Final health differs: {name}")
                self.data["final_health"] = report
            except BaseException as exc:
                errors.append(str(exc))
        self.data.update(status="restore_pending" if errors else "restored", restore_errors=errors)
        self.save()
        if errors:
            raise RuntimeError(f"Restore incomplete; retain journal {self.path}: {errors}")

    @contextmanager
    def transaction(self):
        try:
            self.prepare()  # Unsupported restore must fail before any mutation.
        except BaseException as exc:
            self.data.update(status="refused_before_unload", error=f"{type(exc).__name__}: {exc}")
            self.save()
            raise
        try:
            self.unload()
            yield self
        finally:
            self.restore()

    def watch(self, child_pid):
        """Detect conflicts while our own isolated child is running; never exempt other workers."""
        report = self.observation()
        report["runtimes"] = [r for r in report["runtimes"] if not (
            r["pid"] == child_pid and r["name"] == "gpu_worker")]
        self.assert_idle_configuration(report)
        for name in self.data["models"]:
            if self.same_server(report, name)["state"] != "unloaded_idle":
                raise RuntimeError("Managed model reloaded during benchmark")
