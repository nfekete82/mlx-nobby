# Hybrid final acceptance follow-up

Status: IN PROGRESS. Historical results are not new acceptance evidence.

1. Inventory original files, stashes, worktrees, config, services, PR and rules.
   Use an isolated worktree; preserve the original checkout. Completed.
2. Repair the observed Agent SQLite descriptor leak with transaction/closure
   regressions, verify idle native jobs, then restore Agent availability.
3. Add opt-in backend token/config auditing and full-response acceptance tools.
   Freeze measured code and collect private artifacts with restricted modes.
4. Compare cache-OFF, hybrid baseline, native and diagnostic forced splitting
   over at least 20 synthetic quality tasks with >=2048 output-token allowance,
   fixed history, actual finish reasons and backend identity checks.
5. Run >=20 synthetic local-model RAG attacks with explicit expected results.
   Fix reproducible application defects; document model security limitations.
6. Run a >=7200-second continuous native-server soak with mixed contexts,
   safety checks, memory, cache and latency telemetry. Never bypass admission.
7. Collect >=3 alternating controlled performance pairs; assess complete
   responses, uncertainty and parity separately from first-content latency.
8. Run final medium, browser, compatibility, syntax, i18n and diff checks;
   update documentation and PR #299, push clean commits and inspect final CI.
9. Assign G1–G10 only PASS, FAIL or NOT VERIFIED with evidence. Merge only
   after all PASS and applicable review requirements. Otherwise keep Draft/HOLD.
10. Restore launch settings/config, verify Git and services, preserve private
    outputs and existing untracked files. Report restoration failures explicitly.

New observed blocker: existing Agent could not accept requests (EMFILE), with
124 live SQLite connections to automations.db. SQLite transaction contexts do
not close connections; deterministic closure is necessary before long testing.
