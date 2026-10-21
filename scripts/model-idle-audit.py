#!/usr/bin/env python3
"""Read-only model lifecycle audit. Never unloads models."""

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import runtime_coordinator
from model_idle_policy import IdleState, evaluate_idle_unload


def health(port):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.load(response)


def main():
    try:
        leases = runtime_coordinator.lease_state_snapshot()
    except Exception as exc:
        print("Lease-Status nicht verifizierbar:", exc)
        leases = None

    print("=== MODEL LIFECYCLE AUDIT ===")
    print("Aktion: NUR LESEN, KEIN UNLOAD")

    for role, port in (("chat", 8000), ("router", 8040)):
        print(f"\\n[{role.upper()}] Port {port}")

        try:
            state = health(port)
        except Exception as exc:
            print("Health nicht verfügbar:", exc)
            continue

        loaded = bool(state.get("loaded_models"))
        print("Health:", state.get("status"))
        print("Modell:", state.get("loaded_model"))
        print("Geladen:", loaded)

        # Direct requests bypassing the coordinator are not
        # yet tracked. Unknown means unsafe, never idle.
        direct_requests_verified = False
        activity_timestamp = None

        no_lease = bool(
            leases is not None
            and leases.get("active") is None
            and leases.get("waiting_count") == 0
        )

        decision = evaluate_idle_unload(
            IdleState(
                role=role,
                now=time.monotonic(),
                last_activity=activity_timestamp,
                loaded=loaded,
                idle_verified=direct_requests_verified,
                lease_free=no_lease,
                active_requests=-1,
                pending_requests=-1,
                exclusive_session=True,
                server_identity_verified=False,
            )
        )

        print("Koordinierte Lease frei:", no_lease)
        print("Direkte Requests verifiziert:", direct_requests_verified)
        print("Unload erlaubt:", decision.allowed)
        print("Grund:", decision.reason)

    print("\\nKeine Modelle oder Dienste verändert.")


if __name__ == "__main__":
    main()
