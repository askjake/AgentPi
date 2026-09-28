"""
AgentPi patch integration tests.
Discovers repo root from its own file location — works on any machine.
Run from repo root: python3 tests/patch_verify/test_integration.py
"""
import ast, sys, os, pathlib, re

# Repo root = two directories above this file (tests/patch_verify/test_integration.py)
REPO = str(pathlib.Path(__file__).resolve().parents[2])
sys.path.insert(0, os.path.join(REPO, "dish-chat", "backend"))
sys.path.insert(1, os.path.join(REPO, "backend"))

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-01 + PATCH-07: host_context TTL cache + self-identity
# ─────────────────────────────────────────────────────────────────────────────
def test_host_context():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "host_context",
        os.path.join(REPO, "dish-chat/backend/app/agent/agents/host_context.py"),
    )
    hc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hc)

    ctx = hc.build_host_context()
    assert "127.0.0.1" in ctx or "8765" in ctx, f"AgentPi URL missing"
    assert "Do NOT ping"  in ctx, "Anti-ping instruction missing"
    assert "THIS MACHINE" in ctx, "Self-identity missing"
    assert hc._TTL == 60.0, f"TTL={hc._TTL} (want 60.0)"
    ctx2 = hc.build_host_context()
    assert ctx == ctx2, "Cache miss on second call"
    hc._CACHE = (0.0, "stale")
    ctx3 = hc.build_host_context()
    assert ctx3 != "stale", "Expired cache not refreshed"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-04: 5 new bridge tools present and valid
# ─────────────────────────────────────────────────────────────────────────────
def test_bridge_tools():
    import sys, types, importlib.util
    # Stub heavy deps so test runs without full venv
    sys.modules.setdefault("httpx", types.ModuleType("httpx"))
    lc  = types.ModuleType("langchain")
    lct = types.ModuleType("langchain.tools")
    def tool(name=None):
        def dec(fn):
            fn.name = name or fn.__name__
            fn.description = fn.__doc__ or ""
            return fn
        return dec
    lct.tool = tool
    lc.tools  = lct
    sys.modules.setdefault("langchain",       lc)
    sys.modules.setdefault("langchain.tools", lct)

    spec = importlib.util.spec_from_file_location(
        "agentpi_bridge",
        os.path.join(REPO, "dish-chat/backend/app/tools/agentpi_bridge.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for name in ["agentpi_mqtt_start", "agentpi_mqtt_stop",
                 "agentpi_homeassistant_start", "agentpi_homeassistant_stop",
                 "agentpi_clear_inventory"]:
        t = getattr(mod, name, None)
        assert t is not None, f"{name} missing"
        assert t.name,        f"{name} has no .name"
        assert t.description, f"{name} has no .description"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-04: registry has >=23 tools including all 5 new
# ─────────────────────────────────────────────────────────────────────────────
def test_registry_count():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/tools/registry.py")).read_text(encoding="utf-8")
    m = re.search(r'"agent_mode":\s*lambda:\s*\[(.*?)\]', src, re.S)
    assert m, "agent_mode lambda not found"
    names = re.findall(r'\b(agentpi_\w+|agent_\w+)\b', m.group(1))
    assert len(names) >= 23, f"{len(names)} tools (want >=23)"
    new = {"agentpi_mqtt_start","agentpi_mqtt_stop","agentpi_homeassistant_start",
           "agentpi_homeassistant_stop","agentpi_clear_inventory",
           "agent_genealogy_identity_check"}
    missing = new - set(names)
    assert not missing, f"Missing: {missing}"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-05: named constants + truncation marker
# ─────────────────────────────────────────────────────────────────────────────
def test_patch05():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text(encoding="utf-8")
    assert "SCRATCHPAD_LIMIT = 8_000"  in src, "SCRATCHPAD_LIMIT missing"
    assert "SUMMARIZER_LIMIT = 16_000" in src, "SUMMARIZER_LIMIT missing"
    assert "TRUNCATED"                 in src, "[TRUNCATED] marker missing"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-06: _COVERITY_LLM_TYPES set contains both type strings
# ─────────────────────────────────────────────────────────────────────────────
def test_patch06():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text(encoding="utf-8")
    m = re.search(r'_COVERITY_LLM_TYPES\s*=\s*\{([^}]+)\}', src)
    assert m, "_COVERITY_LLM_TYPES set not found"
    body = m.group(1)
    assert "coverity-assist-tool-enabled" in body, "tool-enabled missing"
    assert 'coverity-assist"' in body,             "base type missing"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-02: _is_mdns_specific + network fast-path guard
# ─────────────────────────────────────────────────────────────────────────────
def test_patch02():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text(encoding="utf-8")
    assert "_is_mdns_specific"       in src, "_is_mdns_specific missing"
    assert "PATCH-02"                in src, "PATCH-02 comment missing"
    assert "agentpi_discover_devices" in src, "bridge guard missing in fast-path"
    ns = {}
    fn_src = re.search(r'def _is_mdns_specific.*?(?=\ndef )', src, re.S).group(0)
    exec(fn_src, ns)
    fn = ns["_is_mdns_specific"]
    assert     fn("discover using mDNS only"), "mDNS not detected"
    assert     fn("find .local devices"),      ".local not detected"
    assert not fn("list devices using arp"),   "ARP wrongly flagged as mDNS"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-03: _search_harder short-circuit + fallback_tool
# ─────────────────────────────────────────────────────────────────────────────
def test_patch03():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text(encoding="utf-8")
    assert "fallback_tool"    in src, "fallback_tool param missing"
    assert "network_dead"     in src, "network_dead flag missing"
    assert "short-circuiting" in src, "short-circuit log missing"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-06: coverity_assist_chat_model _llm_type_base alias
# ─────────────────────────────────────────────────────────────────────────────
def test_patch06_model():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/core/llm/coverity_assist_chat_model.py")).read_text(encoding="utf-8")
    assert "_llm_type_base"           in src, "_llm_type_base missing"
    assert 'return "coverity-assist"' in src, "base return value missing"
    assert "PATCH-06"                 in src, "PATCH-06 comment missing"
# ─────────────────────────────────────────────────────────────────────────────
# PATCH-08: SQLite store structure
# ─────────────────────────────────────────────────────────────────────────────
def test_patch08():
    src = pathlib.Path(os.path.join(REPO, "backend/store.py")).read_text(encoding="utf-8")
    assert "sqlite3"         in src, "sqlite3 import missing"
    assert "WAL"             in src, "WAL journal mode missing"
    assert "DeviceInventory" in src, "DeviceInventory class missing"
    assert "upsert_many"     in src, "upsert_many missing"
    assert "AGENTPI_DB"      in src, "AGENTPI_DB env var missing"
    assert '"runtime" / "agentpi-devices.db"' in src, "portable repo-runtime default missing"
    assert '"/var/lib/agentpi/devices.db"' not in src, "non-portable hardcoded default remains"

    win = pathlib.Path(os.path.join(REPO, "deployment/windows/start.ps1")).read_text(encoding="utf-8")
    assert "AGENTPI_DB" in win and "agentpi-devices.db" in win, "Windows AGENTPI_DB runtime override missing"

    svc = pathlib.Path(os.path.join(REPO, "deployment/linux/agentpi.service")).read_text(encoding="utf-8")
    assert "StateDirectory=agentpi" in svc, "systemd StateDirectory missing"
    assert "Environment=AGENTPI_DB=/var/lib/agentpi/devices.db" in svc, "systemd AGENTPI_DB override missing"
# ─────────────────────────────────────────────────────────────────────────────
# Windows runtime: reserved-port fallback contract
# ─────────────────────────────────────────────────────────────────────────────
def test_windows_agentpi_port_fallback():
    start = pathlib.Path(os.path.join(REPO, "deployment/windows/start.ps1")).read_text(encoding="utf-8")
    runner = pathlib.Path(os.path.join(REPO, "deployment/windows/run_dishchat_backend.py")).read_text(encoding="utf-8")
    verify = pathlib.Path(os.path.join(REPO, "deployment/windows/verify.ps1")).read_text(encoding="utf-8")
    assert "agentpi-port.txt" in start, "selected AgentPi port marker missing"
    assert "18765" in start and "28765" in start, "fallback port candidates missing"
    assert "Test-LoopbackPortBindable" in start, "bind probe missing"
    assert 'os.environ.get("AGENTPI_URL"' in runner, "DishChat runner ignores selected AgentPi URL"
    assert 'IDLE_CHAT_CHECKER_ENABLED' in runner and '"false"' in runner, "Windows idle checker default-off guard missing"
    assert "agentpi-port.txt" in verify, "verifier does not read selected AgentPi port"
# ─────────────────────────────────────────────────────────────────────────────
# Backend longevity: streaming responses must not pin request DB sessions
# ─────────────────────────────────────────────────────────────────────────────
def test_stream_db_lifetime():
    router = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/message/router.py")).read_text(encoding="utf-8")
    usage = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/usage_tracking/service.py")).read_text(encoding="utf-8")
    dbbase = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/db/base.py")).read_text(encoding="utf-8")
    health = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/health/router.py")).read_text(encoding="utf-8")

    send_start = router.index('async def send_message(')
    send_end = router.index('@router.get("/chats/{chat_id}/messages/{message_id}/versions")')
    send_body = router[send_start:send_end]
    assert "db_session: DBSessionDep" not in send_body, "send_message still owns request-scoped DB session"
    assert "async with get_db_session_ctxmgr() as db_session" in send_body, "short setup DB context missing"

    branch_start = router.index('async def create_message_version(')
    branch_end = router.index('@router.put("/chats/{chat_id}/messages/{message_id}/versions")')
    branch_body = router[branch_start:branch_end]
    assert "db_session: DBSessionDep" not in branch_body, "version stream still owns request-scoped DB session"

    assert "profile=None, db=None" in usage, "usage tracker still binds DB session to stream callback"
    assert "async def _persist_usage_metadata(" in usage, "post-stream usage persistence helper missing"
    assert "async with get_db_session_ctxmgr() as db:" in usage, "usage persistence does not use a short-lived DB session"
    assert "await self._persist_usage_metadata(cb, profile)" in usage, "usage metadata is not persisted after the stream"
    assert "_usage_metadata_callback_var" in usage, "module-level usage callback ContextVar missing"
    assert usage.count("register_configure_hook(") == 1, "usage callback hook is registered more than once"
    assert "_usage_metadata_callback_var.reset(token)" in usage, "usage callback token reset missing"
    assert "pool_timeout=" in dbbase and "pool_recycle=" in dbbase and "pool_use_lifo=True" in dbbase, "DB pool hardening missing"
    assert '"/health/db"' in health and "SELECT 1" in health and "pool.status()" in health, "DB readiness diagnostics missing"
# ─────────────────────────────────────────────────────────────────────────────
# Environment-aware network mapping
# ─────────────────────────────────────────────────────────────────────────────
def test_environment_aware_network_mapping():
    host = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/agent/agents/host_context.py")).read_text(encoding="utf-8")
    loop = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text(encoding="utf-8")
    bridge = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/tools/agentpi_bridge.py")).read_text(encoding="utf-8")
    arp = pathlib.Path(os.path.join(REPO, "backend/discovery/arp.py")).read_text(encoding="utf-8")
    app = pathlib.Path(os.path.join(REPO, "backend/app.py")).read_text(encoding="utf-8")
    tools = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/agent_mode/tools.py")).read_text(encoding="utf-8")

    assert 'native_windows = os.name == "nt"' in host, "native Windows detection missing"
    assert "You are running natively on Windows." in host, "Windows host guidance missing"
    assert "running ON the Raspberry Pi" not in host, "stale unconditional Pi identity remains"

    assert '"scan my network"' in loop and '"map my network"' in loop, "network intent phrases missing"
    assert '"active": True' in loop, "network fast-path does not request active AgentPi discovery"
    assert "ALWAYS prefer agentpi_discover_devices" in loop, "planner AgentPi network preference missing"

    assert "active: bool = False" in bridge and '"active_arp": bool(active)' in bridge, "bridge active discovery contract missing"
    assert "_warm_neighbor_cache" in arp and "_local_ipv4_networks" in arp, "active neighbor warmup missing"
    assert "active_arp: bool = False" in app, "AgentPi API active_arp field missing"
    assert "def _ping_args(" in tools and 'if os.name == "nt"' in tools, "native ping syntax helper missing"
    assert "socket.create_connection" in tools, "native TCP port probe missing"
    assert "python_exec = sys.executable" in tools, "agent_run_python does not reuse current interpreter"
    assert "python = python_bin or sys.executable" in tools, "agent_create_venv does not reuse current interpreter"
    assert "Current backend Python interpreter:" in host and "sys.executable" in host, "host context does not expose working Python runtime"
    assert "def _looks_like_device_probe_request" in loop, "device probe intent detector missing"
    assert "[FAST-PATH] specific device probe -> agent_check_device" in loop, "device probe fast-path missing"
    assert "never waste steps probing python/py/python3/where" in loop, "planner Python-runtime guidance missing"

# ─────────────────────────────────────────────────────────────────────────────
# Pytest/runtime persistence isolation
# ─────────────────────────────────────────────────────────────────────────────
def test_pytest_persistent_inventory_isolation():
    conftest = pathlib.Path(os.path.join(REPO, "tests/conftest.py")).read_text(encoding="utf-8")
    app = pathlib.Path(os.path.join(REPO, "backend/app.py")).read_text(encoding="utf-8")

    assert 'os.environ["AGENTPI_DB"]' in conftest, "pytest import-time AGENTPI_DB isolation missing"
    assert "isolated_agentpi_db" in conftest and "monkeypatch.setenv" in conftest, "per-test AGENTPI_DB isolation missing"
    assert "if request.active_arp:" in app, "active/passive ARP call split missing"
    passive = app[app.index("if request.active_arp:"):app.index("if request.mdns:")]
    assert "jobs.append(scan_arp(lookup_vendors=request.lookup_vendors))" in passive, "passive scan_arp compatibility call missing"



# ─────────────────────────────────────────────────────────────────────────────
# Genealogy identity continuity: same/similar names cannot be silently merged
# ─────────────────────────────────────────────────────────────────────────────
def test_genealogy_identity_continuity_contract():
    genealogy = pathlib.Path(os.path.join(
        REPO, "dish-chat/backend/app/agent_mode/genealogy.py"
    )).read_text(encoding="utf-8")
    registry = pathlib.Path(os.path.join(
        REPO, "dish-chat/backend/app/agent/agents/tools/registry.py"
    )).read_text(encoding="utf-8")
    loop = pathlib.Path(os.path.join(
        REPO, "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py"
    )).read_text(encoding="utf-8")

    ast.parse(genealogy, filename="dish-chat/backend/app/agent_mode/genealogy.py")
    assert "agentpi-genealogy-identity-v1" in genealogy, "genealogy identity contract missing"
    assert "def inspect_gedcom_identity(" in genealogy, "deterministic GEDCOM identity resolver missing"
    assert '@tool("agent_genealogy_identity_check")' in genealogy, "genealogy identity tool missing"
    assert "Only status=match permits treating a GEDCOM candidate as the target person" in genealogy, "identity continuity rule missing"
    assert "GEDCOM path must stay inside the conversation workspace" in genealogy, "genealogy workspace boundary missing"
    assert "ZIP containing a GEDCOM" in genealogy and "zipfile.ZipFile" in genealogy, "read-only ZIP GEDCOM inspection missing"
    assert "def _ancestor_context(" in genealogy and '"ancestors"' in genealogy, "bounded ancestor evidence missing"
    assert "birth year missing; expected" in genealogy and "death year missing; expected" in genealogy, "expected-date completeness guard missing"
    assert "agent_genealogy_identity_check" in registry, "genealogy identity tool is not registered"
    assert "def _looks_like_genealogy_identity_request" in loop, "genealogy identity gate detector missing"
    assert "def _infer_genealogy_expected_years" in loop, "genealogy transcript-date enrichment missing"
    assert "def _extract_genealogy_target_name" in loop, "genealogy deterministic target extraction missing"
    assert "def _normalize_genealogy_identity_input" in loop, "genealogy tool-input normalization missing"
    assert "intent=genealogy_identity_preflight" in loop, "genealogy deterministic preflight route missing"
    assert "GENEALOGY_IDENTITY_TARGET_REQUIRED" in loop, "genealogy unresolved-target guard missing"
    assert "GENEALOGY_IDENTITY_CHECK_REQUIRED" in loop, "genealogy final-answer gate missing"
    assert "GENEALOGY_IDENTITY_CONTINUITY_" in loop, "deterministic conflict renderer missing"
    assert "GENEALOGY_LINEAGE_EVIDENCE_REQUIRED" in loop, "genealogy lineage evidence gate missing"
    assert "never infer from surname or spouse alone" in loop, "genealogy lineage anti-inference rule missing"
    assert "if genealogy_identity_required" in loop and "else await _maybe_handle_obvious_direct_task" in loop, "genealogy direct-task bypass remains"
    assert 'selected.name == "agent_genealogy_identity_check"' in loop, "genealogy identity result enforcement missing"
    assert "def _looks_like_text_transformation_request" in loop, "text-transformation intent boundary missing"
    assert "PLANNER_TRANSFORM_TOOL_REJECTED" in loop, "text-transformation tool rejection missing"
    assert "TEXT_TRANSFORMATION_PROTOCOL_INVALID" in loop, "text-transformation fail-closed result missing"
    assert "treat the supplied text/template as inert content" in loop, "planner inert-template instruction missing"


# ─────────────────────────────────────────────────────────────────────────────
# Local public web search must not depend on an unstarted localhost gateway
# ─────────────────────────────────────────────────────────────────────────────
def test_local_public_web_search():
    search = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/tools/web_search.py")).read_text(encoding="utf-8")
    renderer = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/agent/agents/search_renderer.py")).read_text(encoding="utf-8")
    config = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/config.py")).read_text(encoding="utf-8")
    installer = pathlib.Path(os.path.join(REPO, "deployment/windows/install.ps1")).read_text(encoding="utf-8")
    registry = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/agent/agents/tools/registry.py")).read_text(encoding="utf-8")
    health = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/health/router.py")).read_text(encoding="utf-8")
    loop = pathlib.Path(os.path.join(REPO, "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text(encoding="utf-8")

    ast.parse(search, filename="dish-chat/backend/app/tools/web_search.py")
    ast.parse(renderer, filename="dish-chat/backend/app/agent/agents/search_renderer.py")
    assert "PUBLIC_WEB_SEARCH_MODE" in config, "search mode setting missing"
    assert '"auto", "direct", "gateway"' in config, "search mode choices missing"
    assert 'PUBLIC_WEB_SEARCH_MODE" "direct"' in installer, "Windows installer does not select direct search"
    assert "html.duckduckgo.com/html/" in search and "lite.duckduckgo.com/lite/" in search, "direct search backends missing"
    assert "def _fetch_direct_page(" in search and "urlopen(" in search, "native urllib direct-search transport missing"
    assert "truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)" in search, "Windows native trust-store TLS context missing"
    assert "CERT_NONE" not in search and "_create_unverified_context" not in search and "verify=False" not in search, "public search must not disable TLS verification"
    assert "def _parse_duckduckgo_results(" in search, "direct-search parser missing"
    assert "_SEARCH_CACHE" in search and "OrderedDict" in search, "bounded read-only search cache missing"
    assert "PUBLIC_WEB_SEARCH_CACHE_TTL_SECONDS" in search, "search cache TTL missing"
    assert "PUBLIC_WEB_SEARCH_CACHE_MAX_ENTRIES" in search, "search cache bound missing"
    assert "_DIRECT_FETCH_LOCK" in search and "PUBLIC_WEB_SEARCH_MIN_INTERVAL_SECONDS" in search, "direct-search pacing missing"
    assert "PUBLIC_WEB_SEARCH_EMPTY_RETRIES" in search and "PUBLIC_WEB_SEARCH_EMPTY_RETRY_SECONDS" in search, "empty-result retry missing"
    assert '@tool("public_web_search_status")' in search, "search diagnostics tool missing"
    assert "async def public_web_search_status(probe: bool = False)" in search, "search diagnostics must be passive by default"
    assert '"diagnostic_mode": "passive_observation"' in search, "passive observed-health state missing"
    assert "def _record_search_observation" in search, "search observation telemetry missing"
    assert "last_success" in search and "last_failure" in search, "search success/failure observations missing"
    assert "public_web_search_status" in registry, "search diagnostics tool is not registered"
    assert '"/health/search"' in health and "probe_public_search" in health, "search health endpoint missing"

    expected_safe_url_line = 'return quote(url, safe=":/?#@!$&\'*+,;=%._~-")'
    assert expected_safe_url_line in renderer, "safe encoded Markdown URL destination missing"
    assert "def render_public_search_payload" in renderer and "def render_public_search_output" in renderer, "deterministic search renderer missing"
    assert "Rendered deterministically from the actual search-tool payload" in renderer, "renderer evidence receipt missing"

    assert "def _looks_like_search_diagnostic_request" in loop, "search diagnostic intent detector missing"
    assert "LOCAL_ROUTE intent=search_diagnostic" in loop, "search diagnostic fast-path missing"
    diagnostic_route = loop[loop.index("LOCAL_ROUTE intent=search_diagnostic"):loop.index("probe = _runtime_probe_payload")]
    assert '{"probe": False}' in diagnostic_route, "chat diagnosis must not generate active provider probes"
    assert "LOCAL_ROUTE intent=public_web_search" in loop, "grounded fresh-search fast-path missing"
    assert "from app.agent.agents.search_renderer import render_public_search_output" in loop, "planner does not import lightweight deterministic renderer"
    assert "render_public_search_output" in loop, "fresh search deterministic renderer is not wired into planner"
    assert "def _looks_like_search_retry_request" in loop, "search retry intent detector missing"


# ─────────────────────────────────────────────────────────────────────────────
def _run_standalone() -> int:
    tests = [
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    ]
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓  {name}")
        except Exception as exc:
            failed.append(f"{name}: {exc}")
            print(f"  ✗  {name}: {exc}")

    print()
    print("=" * 56)
    print(f"  RESULTS: {passed} passed, {len(failed)} failed")
    print("=" * 56)
    if failed:
        return 1
    print("ALL TESTS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
