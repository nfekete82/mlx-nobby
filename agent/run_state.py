"""Small run-scoped contract, independent of the agent loop."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from threading import Event
import time
import uuid

from agent import code_workspaces


@dataclass(frozen=True)
class RunContext:
    run_id: str
    chat_id: str | None
    workspace_id: str | None
    workspace_root: Path | None
    allowed_roots: tuple[Path, ...]
    started_at: float = field(default_factory=time.time)
    cancellation: Event = field(default_factory=Event, compare=False, repr=False)

    def __post_init__(self):
        if bool(self.workspace_id) != (self.workspace_root is not None):
            raise ValueError("INVALID_WORKSPACE_BINDING")
        root = Path(self.workspace_root).resolve() if self.workspace_root is not None else None
        roots = tuple(Path(path).resolve() for path in self.allowed_roots)
        if roots and (root is None or any(not path.is_relative_to(root) for path in roots)):
            raise ValueError("PATH_OUTSIDE_WORKSPACE")
        object.__setattr__(self, "workspace_root", root)
        object.__setattr__(self, "allowed_roots", roots)

    @classmethod
    def start(cls, run_id=None, chat_id=None):
        workspace = code_workspaces.active_workspace(validate=False)
        root = Path(workspace["root_path"]).resolve() if workspace else None
        return cls(
            run_id=run_id or uuid.uuid4().hex,
            chat_id=chat_id,
            workspace_id=workspace["workspace_id"] if workspace else None,
            workspace_root=root,
            allowed_roots=(root,) if root else (),
        )

    @property
    def cancelled(self):
        return self.cancellation.is_set()

    def cancel(self):
        self.cancellation.set()

    def workspace(self):
        if self.cancelled:
            raise ValueError("RUN_CANCELLED")
        if not self.workspace_id or self.workspace_root is None:
            raise ValueError("WORKSPACE_SELECTION_REQUIRED")
        item = code_workspaces._workspace(self.workspace_id)
        if code_workspaces._root(item) != self.workspace_root:
            raise ValueError("WORKSPACE_CHANGED")
        return item

    def resolve_path(self, path, *, write=False):
        target = code_workspaces._safe(self.workspace(), path, write=write)
        if not any(target.is_relative_to(root) for root in self.allowed_roots):
            raise ValueError("PATH_OUTSIDE_WORKSPACE")
        return target


_CURRENT_RUN = ContextVar("mlx_agent_run", default=None)


def current_run_context():
    return _CURRENT_RUN.get()


@contextmanager
def bind_run_context(context):
    token = _CURRENT_RUN.set(context)
    try:
        yield context
    finally:
        _CURRENT_RUN.reset(token)


def with_run_context(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        context = kwargs.get("run_context") or current_run_context() or RunContext.start()
        with bind_run_context(context):
            return function(*args, **kwargs)
    return wrapped


def workspace_id_for_run():
    context = current_run_context()
    if context is None:
        return code_workspaces.active_workspace_id()
    return context.workspace()["workspace_id"]
