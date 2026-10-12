"""Safe agent-lease diagnostics do not claim unknown external owners."""
from agent.lease_diagnostics import (
    acquired_agent_lease, agent_lease_snapshot, observed_agent_lease,
)


def test_nested_agent_holder_visible():
    with observed_agent_lease("agent") as (_, first):
        acquired_agent_lease(first, "agent")
        with observed_agent_lease("coding") as (evidence, second):
            assert evidence["observed_holder_role"] == "agent"
            assert evidence["observed_agent_holders"] >= 1
            acquired_agent_lease(second, "coding")
            assert agent_lease_snapshot()["holders"] >= 2
    assert agent_lease_snapshot() == {"holders": 0, "waiters": 0}


def test_external_holder_not_invented():
    with observed_agent_lease("agent") as (evidence, _):
        assert evidence["observed_holder_role"] == "unknown"
