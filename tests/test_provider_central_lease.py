"""The actual Provider shares chat leases and releases them on lock cancellation."""
from contextlib import contextmanager
import threading

import runtime_coordinator as coordinator
from agent.model_provider import MLXProvider, ModelRequest, ProviderError
from agent.run_state import RunContext


def test_provider_ownership_and_cancellation_while_model_lock_is_busy(tmp_path, monkeypatch):
    real_lease = coordinator.runtime_lease
    monkeypatch.setattr(coordinator, "runtime_lease", lambda *args, **kwargs:
        real_lease(*args, **{**kwargs, "state_dir": tmp_path / "state"}))
    monkeypatch.setattr(coordinator, "release_idle_image_runtime", lambda *args, **kwargs: {})
    monkeypatch.setattr("agent.model_provider._with_memory", lambda request, context: request)
    model_lock = threading.RLock()
    entered = threading.Event()
    context = RunContext("provider-cancel", None, None, None, ())

    @contextmanager
    def shared_lease(run):
        with coordinator.chat_runtime(run.cancellation, lock_path=tmp_path / "lock") as evidence:
            entered.set()
            yield evidence

    def unexpected(*args):
        raise AssertionError("Cancelled queued provider must not resolve or call a model")

    provider = MLXProvider(model_lock, unexpected, unexpected, runtime_lease=shared_lease)
    errors = []

    def call():
        try:
            provider.complete(ModelRequest([], role="coding"), run_context=context)
        except BaseException as exc:
            errors.append(exc)

    model_lock.acquire()
    thread = threading.Thread(target=call)
    try:
        thread.start()
        assert entered.wait(2)
        snapshot = coordinator.lease_state_snapshot(state_dir=tmp_path / "state")
        assert snapshot["active"]["workload"] == "coding"
        context.cancel()
        thread.join(2)
        assert not thread.is_alive(), "Provider kept holding the shared lease after cancellation"
    finally:
        context.cancel()
        model_lock.release()
        thread.join(2)
    assert len(errors) == 1 and isinstance(errors[0], ProviderError)
    assert errors[0].code == "cancelled"
    snapshot = coordinator.runtime_state_snapshot(state_dir=tmp_path / "state")
    assert snapshot["active"] is None
    assert snapshot["waits_by_workload"]["coding"]["outcomes"]["cancelled"] == 1
    with real_lease(lock_path=tmp_path / "lock", state_dir=tmp_path / "state"):
        pass
