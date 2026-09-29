# Agent Task Mode v1

Agent Task Mode turns the existing coding-agent stack into a deliberate workspace task workflow. It does **not** introduce a second agent runtime.

## Scope

The mode is armed from the chat composer and applies to the next submitted prompt. An active coding workspace is required.

The task runs through the existing `/api/mlx/agent/run` endpoint with `mode=coding` and `workspace_bound=true`. Its execution contract directs the coding agent to:

1. inspect the bound workspace before changing it;
2. form a concise evidence-based implementation plan;
3. prepare mutations with `code_prepare`;
4. let the existing coding runtime run `code_diff` and `code_test` against the isolated patch;
5. request the existing approval-gated `code_apply` only after the prepared patch has been inspected/tested;
6. inspect failing patch tests and perform at most three repair cycles through the same prepare/diff/test/approval path;
7. rely on the existing apply verification after approval;
8. prefer workspace/code tools over unrestricted shell execution;
9. finish with changed files, isolated test status, apply/verification status and patch/diff information while preserving `code_revert` rollback semantics.

## Safety model

Task Mode reuses the existing ToolRegistry, PermissionEngine, approval store, coding workspaces, snapshots and patch implementation. It therefore cannot bypass the normal approval requirement for a protected mutation.

Task Mode v1 intentionally requires an explicitly active coding workspace and does not silently fall back to the process working directory. Attached files are intentionally rejected in v1 instead of being silently ignored; the first release is scoped to the active coding workspace.

## Frontend

`frontend/assets/chat/agent-task-mode.js` owns the one-shot composer toggle, active-workspace validation, task progress polling and creation of the normal `agent_run` message shape. Existing agent-card rendering and approval actions continue to work unchanged. A small approval adapter keeps the user-visible task goal stable after an approval resume, while the backend continues with the full internal execution goal.

The module has isolated styling and language files:

- `frontend/assets/chat/agent-task-mode.css`
- `frontend/i18n/agent-task-mode.de.json`
- `frontend/i18n/agent-task-mode.en.json`

## Follow-ups

Potential v1.x additions include richer task-phase rendering, explicit per-task rollback buttons, durable task history across chats, attachment support and deterministic server-side repair-attempt accounting.
