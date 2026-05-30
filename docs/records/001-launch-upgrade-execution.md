# Execute-Theorem Report: TickTick MCP Launch Upgrade

Source spec: `SPEC-ticktick-mcp-launch-upgrade.md` (retire V2, add launch dashboard, harden move into batch move). Executed 2026-05-30 against the deployed code on `main` (fast-forwarded to `origin/main` @ d68a124 first, since the local checkout was 8 commits behind the deployed state).

## Executive Summary
- **Final condition:** All three spec moves implemented and verified. 22 tools register (down from 30: 10 V2 tools removed, 2 added). Full suite green (27 passed). Ruff clean.
- **Goal achieved?** Yes — plus a discovered, required prerequisite fix (see Deviations P0).
- **Production readiness:** High for the OAuth task surface. All behavior validated through tests + introspection; live TickTick API not exercised (no token in this environment — all tests use mocks).
- **Biggest remaining risk:** The dedicated batch-move endpoint path `/project/task/move` could not be confirmed against developer.ticktick.com (docs are a JS SPA that returned a 404 shell to the scraper). Mitigated: `move_tasks` falls back to a verified per-task move on any 4xx, so an unavailable endpoint degrades gracefully and never reports a silent success.
- **Recommended next action:** Smoke-test `ticktick_move_task` / `ticktick_batch_move` and `ticktick_launch_dashboard` against a live token to confirm which move path the token takes; then commit on a feature branch and redeploy.

## Checklist Reconciliation
| ID | Original task | Status | Evidence | Tests/results | Notes |
|---|---|---|---|---|---|
| P0 | (discovered) Fix tool registration under pydantic 2.12 | completed | `from __future__ import annotations` removed from `server.py` | introspection: 22 tools register (was: NameError, 0) | Prerequisite for the spec's own verification gate; also a latent prod bug |
| M1.1 | Delete `v2_client.py` | completed | `git rm ticktick_mcp/v2_client.py` | leftover sweep CLEAN | |
| M1.2 | Remove V2 tools/wiring/helper from `server.py` | completed | 10 tools, lifespan V2 init/close, `_get_v2_client`, instructions, docstring removed | 22 tools register | |
| M1.3 | Remove V2 input models from `models.py` | completed | Focus/Habit/Tag models removed | model tests pass | |
| M1.4 | Drop `TICKTICK_USERNAME`/`PASSWORD` from `.env.example` | completed | `.env.example` diff (-4) | — | |
| M1.5 | Delete V2 tests; clean stray mocks | completed | `git rm tests/test_v2_client.py`; `ticktick_v2` keys removed from 2 mock helpers | 27 passed | |
| M1.6 | Clarify tags survive via OAuth task body | completed | server instructions + CLAUDE.md Auth section | — | |
| M2.1 | `filter_by_tags` + `group_by_horizon` in `queries.py` | completed | functions added verbatim per spec | 5 new query tests pass | |
| M2.2 | `LaunchDashboardInput` model | completed | added (ResponseFormat enum + `_STRICT_CONFIG`) | 2 model tests pass | Deviation D2 |
| M2.3 | `format_dashboard_md` in `formatting.py` | completed | added; runs through `truncate_response` | dashboard tool test asserts grouping | |
| M2.4 | `ticktick_launch_dashboard` tool | completed | added after weekly_review; fetches only requested project_ids | tool test: tag filter + horizon grouping | adapted to `_get_client(ctx)` |
| M3.1 | `move_tasks` in `client.py` | completed | dedicated endpoint + verified fallback | 3 client tests (success / fallback / silent-noop) | Deviation D4 |
| M3.2 | `TaskMove` + `BatchMoveInput` models | completed | TaskMove defined first | 2 model tests pass | Deviation D3 |
| M3.3 | `ticktick_batch_move` + `move_task` as thin wrapper | completed | both call `client.move_tasks`; move_task surface unchanged | introspection + move_task path | |
| D1 | Update `CLAUDE.md` | completed | 13→22 tool table, V2 note dropped, config path fixed | — | Deviation D7 |
| D2 | Run introspection check | completed | 22 tools listed | pass | |
| D3 | Tests for `filter_by_tags` + `group_by_horizon` | completed | `test_queries.py` (+77 lines) | pass | + model + tool tests (exceeds) |
| D4 | Sync root `server.py`; full suite | completed | root copy byte-identical | 27 passed | Deviation D6 |

## Changes Made
| Area | Files | Summary | Why |
|---|---|---|---|
| Registration fix | `ticktick_mcp/server.py` (+root) | Removed `from __future__ import annotations` | pydantic 2.12 + FastMCP can't resolve stringized tool-param annotations |
| V2 retirement | `v2_client.py`, `server.py`, `models.py`, `.env.example`, `tests/` | Deleted client, 10 tools, 10 models, creds, V2 tests | Spec Move 1 |
| Launch dashboard | `queries.py`, `models.py`, `formatting.py`, `server.py` | `filter_by_tags`, `group_by_horizon`, `LaunchDashboardInput`, `format_dashboard_md`, `ticktick_launch_dashboard` | Spec Move 2 |
| Batch move | `client.py`, `models.py`, `server.py` | `move_tasks` (dedicated + verified fallback), `TaskMove`/`BatchMoveInput`, `ticktick_batch_move`, rewired `ticktick_move_task` | Spec Move 3 |
| Docs | `CLAUDE.md`, `docs/records/001-...md` | 22-tool surface, fixed stale path, this report | Spec docs + skill deliverable |
| Tests | `test_queries.py`, `test_models_queries.py`, `test_launch_and_move_tools.py` | 13 new tests | Spec test req + adaptation coverage |

## Tests and Validation
| Command/check | Result | Notes |
|---|---|---|
| `uv run python -c "...mcp._tool_manager._tools"` | PASS — 22 tools | Spec's introspection gate; was failing (NameError) pre-P0 |
| `uv run pytest` | PASS — 27 passed | Was 6 failed / 11 passed at baseline (NameError) |
| `uvx ruff check ticktick_mcp/` | PASS — all checks passed | No unused imports / lint issues |
| `python -m py_compile` (all .py) | PASS | |
| `diff server.py ticktick_mcp/server.py` | identical | Root duplicate kept in sync |
| Live TickTick API call | NOT RUN | No `TICKTICK_ACCESS_TOKEN` in this environment; all tests mock the client |

## Deviations from the literal spec (all transparent, all to hit-or-exceed the bar)
- **P0 — Removed `from __future__ import annotations` from `server.py` (not in spec).** Discovered prerequisite: with `pydantic 2.12.5` + `fastmcp 2.14.5`, the future import makes every `@mcp.tool` fail schema generation (`NameError` on the input model), so the spec's own introspection check could not pass and the server registered 0 tools. Also a latent production bug — `uv.lock` pins pydantic 2.12.5 and the Dockerfile deploys via `pip install .` against `pydantic>=2.0`, so the next Railway rebuild would have hit it. Verified the one-line removal fixes registration (Python 3.12 makes the union/generic syntax native, so it's safe).
- **D2 — `LaunchDashboardInput`/`BatchMoveInput` use `ResponseFormat` enum + `_STRICT_CONFIG`** instead of the spec's `Literal["markdown","json"]` + inline `ConfigDict(extra="forbid")`. The spec explicitly said "following the existing `extra='forbid'` convention"; `_STRICT_CONFIG` is that convention plus `str_strip_whitespace`/`validate_assignment`, and the enum keeps `== ResponseFormat.JSON` comparisons uniform with all other tools. `match` keeps `Literal["any","all"]` (no codebase enum for it).
- **D3 — `TaskMove` defined before `BatchMoveInput`** (spec listed them reversed). Pydantic v2 must resolve `list[TaskMove]` at class-build time.
- **D4 — `move_tasks` is dual-path** (dedicated endpoint, then verified per-task fallback) rather than only the dedicated POST in the spec's client snippet. The spec's Move 3 body requires the verified fallback ("surface a clear error ... rather than reporting a silent success"), so this is the spec requirement, not extra scope.
- **D5 — Dashboard JSON path uses `format_json(buckets)`** (codebase convention, indented, runs through `truncate_response`) instead of bare `json.dumps(buckets, default=str)`. Same data, consistent with every other JSON tool, and avoids a new import.
- **D6 — Kept the stray root `server.py` in sync rather than deleting it.** It is a byte-identical duplicate from an "Add files via upload" commit; the Dockerfile copies only `ticktick_mcp/`, so it is not deployed. I did not create it, so I did not delete it unilaterally — flagged in CLAUDE.md Gotchas as removable.
- **D7 — Updated `CLAUDE.md` beyond the literal instruction.** The on-disk file was more stale than the spec implied (claimed 13 tools, omitted the smart-query/standup tools entirely, and had a dead iCloud `--directory` path). Fixed the path, added `queries.py`, documented the `MCP_TRANSPORT` default, and recorded the decisions — consistent with the spec's premise that CLAUDE.md is stale.

## Incomplete or Blocked Work
- **Live-API confirmation of the move endpoint** — not done. Why: no token in this environment + docs SPA un-scrapable. Evidence: firecrawl scrape of developer.ticktick.com returned a 404 shell. Risk: low (verified fallback covers it). Next action: run a real move with a token and observe whether the dedicated path 2xx's or the fallback engages. Owner: maintainer with a token.
- **Commit/push** — not done (no user request). Changes are in the working tree; the two V2 deletions are staged (`git rm`), everything else unstaged. On `main`; branch before committing per repo convention.

## New Findings
- **New tensions:** `uv.lock` (pydantic 2.12.5) vs. Dockerfile (`pip install .`, range-resolved) — the lock and the deployed resolve can diverge; the future-annotations bug is the first symptom.
- **New assumptions:** the dedicated `/project/task/move` path is the spec author's stated path; treated as unconfirmed and made non-fatal.
- **New gaps:** the local `.venv` was broken (hardcoded to the old iCloud path after the repo moved to `Tech Dev Local/`); recreated with `uv sync`. The repo carries a duplicate root `server.py`.
- **New refactor opportunities:** delete the root `server.py` duplicate; consider pinning pydantic in `pyproject.toml` so deploy matches the lock.
- **New tests needed:** a live integration smoke test gated on a token env var.

## Production Gate Review
- [x] Tests pass or failure is explained. — 27 passed; live API not run (explained).
- [x] Behavior preserved where required. — OAuth task/project surface unchanged; `ticktick_move_task` surface identical (now verified internally).
- [x] Rollback/revert path considered. — All changes in working tree, uncommitted; `git checkout`/`git restore` reverts cleanly.
- [x] Docs/ADR updated or explicitly deferred. — CLAUDE.md updated; this Record written.
- [x] No hidden TODOs or silent deferrals. — Deviations enumerated above.
- [x] Security/performance risks considered. — Dashboard fetches only requested projects (cheap); batch capped at 50; no secrets touched (V2 creds removed).
- [x] Follow-up plan proposed if needed. — Live smoke test + commit-on-branch.

## Compound Engineering Effect
- **Tests added:** +13 (5 query, 4 model, 4 tool/client); net test count 17→27 (3 V2 removed).
- **Docs:** CLAUDE.md refreshed to reality; this execution Record.
- **Reusable patterns:** verified-move (`get → update → re-read`) is a reusable guard against silent API no-ops; `group_by_horizon` reuses existing date filters.
- **Future plan seeds:** remove root `server.py`; pin pydantic for deploy parity.

## Suggested Next Steps
1. Smoke-test the 3 changed surfaces against a live token (move, batch_move, launch_dashboard).
2. `git switch -c launch-upgrade && git commit` the change set; open a PR.
3. Redeploy to Railway; confirm tools register in the deployed env (the P0 fix is what makes this safe).
4. (Optional) Delete the root `server.py` duplicate and pin pydantic in `pyproject.toml`.
