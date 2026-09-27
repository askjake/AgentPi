# AgentPi execution boundary repair and MCOP reuse plan

Date: 2026-09-27. Reviewed baseline: `08b1096b883284d6e577272f860019e057b919f3`, branch `feature/bugfix-10-gaps`.

## Status and scope

This change repairs local task routing and planner-to-tool dispatch. It does not enable MCOP children, change provider credentials, widen the shell allowlist, migrate databases, or install a new GUI. MCOP and cache integration below is a staged design, not a claim of completed integration.

The reviewed planner source was reconstructed into an isolated test directory from the conversation's historical source archive and the pinned GitHub source. Its Git blob was checked against `dfaa82312a0f669b2794b58d3fb97fea9fd93b49` before changes. No live user's repository, database, or network was used in the tests.

## Reproduced defects

1. The public-information shortcut matched the word `current`. The request to write and run Python that reports the current working directory therefore selected web search before Python execution. A network error on that unrelated path is not evidence that Python is unavailable.
2. Local application requests mentioning cameras or current state could enter broad video/web/shell shortcuts before the planner considered the actual artifact task.
3. The action decoder accepted entire JSON responses and certain fenced/single-line objects, but missed a prose-prefixed multiline tool directive. The caller returned undecodable planner content as the final answer. This can display internal tool JSON rather than execute it.
4. Synchronous tool adapters ran directly on the event-loop thread. A blocking adapter could stall unrelated ASGI work.
5. A TypeError raised inside a callable tool triggered a second invocation using another argument convention. That is unsafe for operations with side effects.

The posted GUI transcript contains incomplete tool-argument text and no authoritative file-write, test, or shortcut receipt. The exact on-disk artifact was not recovered from that transcript. Its visible URLs also omit `/rest/api/v1`; the pinned AgentPi scan route is `/rest/api/v1/discovery/scan`, not `/discover`. Manual device creation, update, deletion, login, and device control must each be checked against a real supported API before being presented as working features.

## Implemented repair

- Local Python/artifact intent is considered before generic word-based shortcuts.
- The exact finite runtime-probe request invokes the already-bound `agent_run_python`, uses the current chat identity and backend interpreter, and returns actual executor output. It does not require a provider call, web search, or AgentPi HTTP request. Broader script requests remain planner-driven.
- The decoder accepts one complete unambiguous JSON action, including a prose prefix, and rejects truncated, oversized, duplicate-key, nonfinite, malformed, or ambiguous actions. It never reconstructs missing code or executes nested fragments.
- Invalid plans get at most two protocol attempts within the existing planner-step budget. Rejected plans do not execute; the final status explicitly distinguishes them from any tools that already returned.
- Tool dispatch logs name and started/returned/raised state without logging code, tokens, or full inputs. Returned does not mean succeeded: legacy tools can return an error string.
- Synchronous adapters execute through `asyncio.to_thread`. Calling convention selection precedes execution; an internal TypeError is not retried as another invocation.
- Planner guidance separates artifact preparation, syntax tests, finite smoke tests, shortcut creation, and persistent GUI launch. It discourages placing an entire application in one bounded planner response.

This is not a universal semantic intent engine or an exactly-once distributed executor. Generic workflow receipts, cancellation-aware subprocess management, durable tasks, and idempotency remain follow-up work.

## Verification performed

`tests/test_planner_execution_boundary.py` executes the production planner function bodies with external provider/message imports isolated. It also executes the real `agent_run_python` implementation body and its workspace helpers in a temporary directory. These are explicit test doubles at the provider boundary, not live LLM tests.

- Seven selected regressions fail against the exact baseline: four local-routing cases, prefixed JSON dispatch, synchronous event-loop blocking, and TypeError double invocation.
- The repaired focused suite passes 31 tests on Linux, Python 3.13.5, pytest 9.0.2.
- The exact runtime prompt creates a script and returns the actual test interpreter, hostname, version, and working directory with exit code zero.
- No external HTTP service, production SQLite/PostgreSQL database, or network scan was used.

Native Windows UI execution, the complete application suites in the deployed dependency environments, provider-backed conversations, and a long-running concurrency soak still require host qualification. Source checks and health endpoints alone do not establish those outcomes.

## Windows qualification

From the existing CMD prompt in the clone:

```bat
call deployment\windows\qualify-execution-boundary.cmd
```

This runs the focused suite, root suite, DishChat Windows suite, and standalone patch verifier, stopping on the first nonzero exit. It does not restart services by default.

After preserving any important live conversations, add `--restart` to run the existing stop/start/verify scripts only after every test succeeds:

```bat
call deployment\windows\qualify-execution-boundary.cmd --restart
```

The current Windows MemorySaver implementation loses in-memory graph checkpoints on restart. A successful SQL backup or healthy PostgreSQL endpoint does not make those checkpoints durable. This repair does not change that storage behavior.

Retest the original runtime-probe request in the UI. Expect actual executor output, not illustrative Unix output or a request to install Python. A missing tool binding must produce a specific blocked result rather than an unrelated network fallback.

## JakeBot work reviewed as design inputs

Prior user-provided artifacts include:

- `Jakes-agent-efficiency-fix-parallelism-antigarble-20260903.patch`, including `docs/MCOP_METHODOLOGY.md` and adaptive prompt changes;
- `jakebot_tool_call_reliability.patch`, including scoped tool binding and execution-policy integration;
- `JakeBot_3090_AI_Observability_Q2_2026_Analysis.md`, a July 2026 source-analysis report covering tiered history, tool-result compression, model/tool caching, and limitations;
- prior MCOP child-lifecycle/acceptance records identifying capability gates and bounded output.

These are historical artifacts, not a fresh audit of the live JakeBot tree. No private repository code, deployment configuration, endpoint credential, or cloud account configuration is copied by this commit.

MCOP means Multi-Conversation Orchestration Protocol here. It orchestrates work above local tools and MCP integrations; it is not another spelling of MCP.

## Proposed integration sequence

### 1. Capability and execution contracts

Generate a capability snapshot from actual runtime bindings: host platform, interpreter, tool name, input schema, execution location, readiness, authorization scope, and side-effect class. Installed, allowed, bound, and healthy are different facts. Use a narrow task-relevant model-facing catalog; the execution registry remains the authorization boundary.

Represent dispatch results with explicit states such as blocked, failed, partial, and succeeded. Include task/tool IDs, timing, input/output digests, artifact references, and validation results. Do not infer success from a friendly sentence or HTTP 200 alone. Preserve original evidence before creating previews.

### 2. Durable task and conversation state

Store task phases, artifact paths/hashes, verification outcomes, and resumable work before adding child execution. Restore conversation graph state using a compatible persistent checkpointer rather than relying on Windows MemorySaver. Validate encryption, ownership, restart readback, branching, deletion, schema compatibility, and recovery separately. Do not silently replace lost history with an apparent successful empty conversation.

### 3. Bounded artifact workflows

Port JakeBot's file-first and bounded-preview approach. Large application generation should write small independently validated files or chunks, inspect actual API schemas, and persist a phase receipt before advancing. Never repair truncated JSON by guessing the missing Python source.

For a device-management application, first implement and test the required APIs. A desktop shortcut opening a supported browser UI is preferable to launching Tkinter from a request worker. A shortcut receipt and an interactive desktop launch test are separate acceptance checks. Do not claim a discovered host is controllable without a verified device-specific capability and authorized credentials.

### 4. Scoped caching and context pressure management

Reuse the useful cache types, not a blanket output cache:

| Cache | Required key and lifecycle |
| --- | --- |
| Tool schemas/profile | Registry generation, provider, policy/owner scope; invalidate on capability or credential changes |
| Host capabilities | Host/interpreter identity, short TTL; report timestamp; never turn cache contents into permission |
| File/API schema reads | Content digest or server version/ETag plus authorization scope |
| Model clients | Provider/model/options and credential generation; evict on expiry/rotation |
| Read-only observations | Explicit TTL, source and stale marker; force refresh when requested |
| Provider prompt cache | Provider-specific support and measured cache token metadata; no assumed Bedrock equivalence through a proxy |

Do not cache script execution, writes, logins, device controls, or active discovery as though a fresh action occurred. Do not store credentials or mix results across owners/chats. All in-process caches need bounded size and cleanup.

The earlier audit identified a process-global codebook and an unbounded per-chat budget store. Those designs should not be transplanted unchanged. Tiered memory should preserve recent user instructions and tool-call/result pairs and keep raw evidence retrievable. Report measured hit rate, latency, input tokens, and invalidation behavior instead of promising a savings percentage.

### 5. Optional MCOP workers

Only after the parent can reliably execute, record, validate, and resume tasks should MCOP child execution be enabled. Preserve a durable parent-only option. Child permissions must be a subset of parent permissions; capabilities must pass preflight; recursive spawning should remain disabled by default.

Parallelize proven-independent reads or disjoint artifact work, not operations sharing mutable state or devices. Bound concurrency, iteration counts, time, and tokens. Deduplicate requests and stop no-progress loops. Workers return bounded ToolEvidencePacket-style evidence; a verifier checks results against acceptance criteria before the parent declares completion.

## Acceptance criteria for the larger port

- The runtime diagnostic works when external search and optional visualization are unavailable.
- An incomplete GUI tool action cannot be mistaken for an executed action.
- No missing capability silently widens permissions or redirects into unrelated tools.
- A canceled stream does not strand subprocesses, DB sessions, or worker capacity.
- Task/artifact state and chat checkpoints survive a controlled restart.
- Active device probes are fresh; cached observations carry timestamps and scope.
- Concurrent children cannot cross owner/workspace boundaries or overwrite one another's artifacts.
- Live tool bindings and model-facing schemas agree before and after registry refresh.
- End-to-end artifact creation, syntax check, service/API check, and shortcut behavior have independent receipts.
