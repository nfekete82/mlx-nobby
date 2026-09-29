# Agent Task Mode v1

Agent Task Mode turns the existing coding-agent stack into a deliberate workspace task workflow. It does **not** introduce a second agent runtime.

## Scope

Workspace selection is now the mode boundary:

- **No active coding workspace** → normal chat.
- **Active coding workspace** → every submitted prompt runs through the workspace-bound coding agent.

There is no separate `Chat | Task` switch. Selecting a workspace means the user wants to work in that project; closing the workspace returns immediately to normal chat.

Workspace mode does **not** mean every prompt must mutate files. The agent first determines whether the request is read-only or mutating:

- explanations, searches, reviews, diagnostics and code analysis stay read-only;
- requested code or file changes use the protected patch workflow.

The workspace task runs through the existing `/api/mlx/agent/run` endpoint with `mode=coding` and `workspace_bound=true`. Its execution contract directs the coding agent to:

1. inspect the bound workspace first;
2. decide whether the request is read-only or requires a mutation;
3. answer read-only requests from workspace evidence without preparing a patch;
4. for mutations, prepare changes with `code_prepare`;
5. let the existing coding runtime run `code_diff` and `code_test` against the isolated patch;
6. request the existing approval-gated `code_apply` only after the prepared patch has been inspected/tested;
7. inspect failing patch tests and perform at most three repair cycles through the same prepare/diff/test/approval path;
8. rely on the existing apply verification after approval;
9. prefer workspace/code tools over unrestricted shell execution and preserve `code_revert` rollback semantics.

## Safety model

Workspace mode reuses the existing ToolRegistry, PermissionEngine, approval store, coding workspaces, snapshots and patch implementation. It therefore cannot bypass the normal approval requirement for a protected mutation.

An explicitly active coding workspace is always required. The agent never silently falls back to the process working directory. Attached files are intentionally rejected in v1 instead of being silently ignored; the first release is scoped to the active coding workspace.

Read-only prompts never need approval because they do not prepare or apply a patch. Mutation prompts retain the full `prepare → diff → isolated test → approval → apply → verify` path.

## Frontend

`frontend/assets/chat/agent-task-mode.js` observes the active workspace state, intercepts composer submissions only while a workspace is active, polls task progress and creates the normal `agent_run` message shape. When no workspace is active, it does not intercept the composer and the normal chat path remains unchanged.

Existing agent-card rendering and approval actions continue to work unchanged. A small approval adapter keeps the user-visible task goal stable after an approval resume, while the backend continues with the full internal execution goal.

The language files are:

- `frontend/i18n/agent-task-mode.de.json`
- `frontend/i18n/agent-task-mode.en.json`

The Git-style comparison view remains presentation-only and consumes the existing `code_diff` result. It does not alter patch, test, approval or apply semantics.

## Follow-ups

Potential v1.x additions include richer task-phase rendering, explicit per-task rollback buttons, durable task history across chats, attachment support and deterministic server-side repair-attempt accounting.
