# Agent Task Mode v1

Agent Task Mode turns the existing coding-agent stack into a deliberate workspace task workflow. It does **not** introduce a second agent runtime.

## Scope

The mode is armed from the chat composer and applies to the next submitted prompt. An active coding workspace is required.

The task runs through the existing `/api/mlx/agent/run` endpoint with `mode=coding` and `workspace_bound=true`. Its execution contract directs the coding agent to:

1. inspect the bound workspace before changing it;
2. form a concise evidence-based implementation plan;
3. prepare mutations with `code_prepare`;
4. use the existing approval-gated `code_apply` path;
5. run workspace tests with `code_test` after an approved apply;
6. inspect failing tests and perform at most three repair cycles;
7. prefer workspace/code tools over unrestricted shell execution;
8. finish with changed files, test status and patch/diff information;
9. preserve `code_revert` rollback semantics.

## Safety model

Task Mode reuses the existing ToolRegistry, PermissionEngine, approval store, coding workspaces, snapshots and patch implementation. It therefore cannot bypass the normal approval requirement for a protected mutation.

Task Mode v1 intentionally requires an explicitly active coding workspace and does not silently fall back to the process working directory.

## Frontend

`frontend/assets/chat/agent-task-mode.js` owns the one-shot composer toggle, active-workspace validation, task progress polling and creation of the normal `agent_run` message shape. Existing agent-card rendering and approval actions continue to work unchanged.

The module has isolated styling and language files:

- `frontend/assets/chat/agent-task-mode.css`
- `frontend/i18n/agent-task-mode.de.json`
- `frontend/i18n/agent-task-mode.en.json`

## Follow-ups

Potential v1.x additions include richer task-phase rendering, explicit per-task rollback buttons, durable task history across chats, attachment support and deterministic server-side repair-attempt accounting.
