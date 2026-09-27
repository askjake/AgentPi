# Live planner wiring and evidence repair

Baseline: `3e88df14146fd4962d5738a8d6092edcc124211b`, branch `feature/bugfix-10-gaps`.

## What the passing tests missed

The prior repair modified and tested `app/agent/agents/coverity_tool_loop_token_limit.py`. Ordinary chat (`agentic_rag.py`) imported the separate, stale `coverity_tool_loop.py`. Agent Mode imported that entry point but bypassed it by calling the bound model directly. Consequently, a unit-tested runtime probe could still be sent to unrelated web search in the UI, and malformed planner actions could still appear as prose.

This was a qualification gap in the previous repair. A passing file-specific test suite or a healthy HTTP process did not prove which planner the live graph called.

## Changes

1. Replace the stale implementation at the actual import path with a small shared entry point delegating to the repaired canonical implementation. The canonical implementation is unchanged by this repair.
2. Make Coverity Agent Mode actually call the same entry point. Native structured-tool providers retain their existing branch.
3. Answer MCOP capability questions from explicit implementation status, not LLM speculation. MCOP is **Multi-Conversation Orchestration Protocol** and is not implemented in this revision. Ordinary tool calls do not constitute an MCOP demonstration. Requests to implement MCOP still reach planning.
4. For artifact-completion follow-ups, read the current conversation's configured workspace. Return observed paths, byte counts and bounded SHA-256 readback, not an inferred completion certificate. Local artifact-creation responses containing completion language are replaced by readback. Existing files are not proof of creation this turn, syntax validation, functional acceptance, or a Desktop shortcut.
5. Add `GET /rest/api/v1/health/execution`. It identifies the loaded entry point and canonical implementation, startup-captured source digests, both graph bindings, process PID, and bounded invocation counters. It does not run tools, expose credentials/user paths, or prove provider readiness.
6. The Windows helper checks the running endpoint against local source digests after restart. A healthy old process, missing route, mismatched graph binding, or stale loaded source fails this check.

Artifact readback does not search the whole machine, execute files, follow workspace symlinks/junctions, create directories, or read `.env` content. It is bounded to 512 scanned entries and 8 MiB of hashing. A partial/blocked scan is labeled explicitly. Files outside the checked workspace may still exist; absence there is not global absence.

This scoped guard is not a universal factuality verifier. Generic model prose, all non-Coverity providers, device manufacturer inference, functional GUI acceptance, and durable task receipts require further work. A workspace directory and shell allowlist are not a security sandbox. MCOP, durable Windows checkpoints, and the complete requested Home Network Manager are not implemented by this patch.

## Tests and limitations

Source identities checked against the pinned repository blobs:

- Chat graph: `9b142f9df15f38ccd05ac259b4dcdf37d021b526`.
- Old live planner: `36b9d7c67f39962011d02e7017d55b51453d789c`.
- Agent Mode node: `fbce4d24c460a0b3cc54833b8336cd6e115afeb4`.
- Unchanged repaired canonical planner: `60624f82b90ccef51b64323b42fbb80e529fdad4`.

The canonical file was reconstructed from the earlier source archive and exact review diff, then verified by Git blob hash. The untouched caller files match their pinned blob hashes. The working container could not clone GitHub directly, so this is not a claim that a full fresh clone/dependency installation was tested here.

On Linux/Python 3.13.5:

- Two new caller-level regressions fail against the baseline, reproducing unwanted model/network routing in ordinary chat and Agent Mode.
- The repaired portable suite passes **20 tests**, including actual module imports and a real local Python subprocess.
- The suite tests MCOP non-implementation, no-tool demonstration, missing artifact claims, actual file hashing, bounded readback, traversal/symlink rejection, and stale runtime-identity rejection.

The portable suite stubs external provider/framework/registry boundaries; it does not AST-select the planner or caller being tested. The separate deployed suite `tests_windows/test_live_graph_entrypoint.py` uses real LangGraph, real message classes, real registry bindings, and the real `agent_run_python`; only providers, telemetry, and model-option application are substituted. It includes a compiled chat-graph execution. That suite and native Windows service qualification are **pending the host run**, not claimed as passed in the Linux container.

## Windows procedure

Preserve important in-memory conversations before restart; Windows checkpoint durability is unchanged.

```bat
cd /d C:\Users\Systems1\Documents\AgentPi && git pull --ff-only origin feature/bugfix-10-gaps && call deployment\windows\qualify-execution-boundary.cmd --restart
```

The helper stops on the first failure. It runs root and deployed tests before restart and performs the new live identity check after existing service/DB checks. Look for `LIVE_PLANNER_IDENTITY_PASS` and `EXECUTION_BOUNDARY_QUALIFICATION_PASS`.

In the UI, the exact runtime-information Python prompt must return real executor output prefixed `Local agent_run_python result`. A connection-error summary or illustrative Unix output is not acceptance.

A description of MCOP must explicitly say it is not implemented. A `did you finish?` follow-up to a file task must return readback (`ARTIFACT_READBACK_ONLY`) rather than invented byte counts or shortcut claims.

A bare relative filename in CMD is resolved from that terminal's current directory. A Markdown escape such as `home\_manager.py` is not the filename `home_manager.py`. Neither a wrong-path terminal error nor a model's completion sentence substitutes for an actual absolute-path file receipt.
