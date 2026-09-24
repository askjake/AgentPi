"""
AgentPi patch integration tests.
Verifies all patches without a live Pi service.
Run: python3 test_integration.py
"""
import sys, os, asyncio, pathlib, tempfile, re

REPO  = os.environ.get("REPO", "/tmp/agentpi_patches")
PATCH = "/tmp/agentpi_patches"
sys.path.insert(0, PATCH + "/dish-chat/backend")
sys.path.insert(1, PATCH + "/backend")

PASS = []
FAIL = []

def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  ✓  {name}")
    except Exception as e:
        FAIL.append(f"{name}: {e}")
        print(f"  ✗  {name}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-07 + PATCH-01: host_context TTL cache + self-identity
# ─────────────────────────────────────────────────────────────────────────────
def test_host_context():
    import importlib, importlib.util, types

    spec = importlib.util.spec_from_file_location(
        "host_context",
        PATCH + "/dish-chat/backend/app/agent/agents/host_context.py"
    )
    hc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hc)

    ctx = hc.build_host_context()
    assert "127.0.0.1" in ctx or "8765" in ctx, f"AgentPi URL missing\n{ctx[:200]}"
    assert "Do NOT ping" in ctx,                 "Anti-ping instruction missing"
    assert "THIS MACHINE" in ctx,                "Self-identity missing"
    assert hc._TTL == 60.0,                      f"TTL wrong: {hc._TTL}"
    # cache hit
    ctx2 = hc.build_host_context()
    assert ctx == ctx2, "Cache miss on second call"
    # force expire
    hc._CACHE = (0.0, "stale")
    ctx3 = hc.build_host_context()
    assert ctx3 != "stale", "Expired cache not refreshed"

check("PATCH-01+07 host_context self-identity + TTL cache", test_host_context)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-04: 5 new bridge tools exist and are valid
# ─────────────────────────────────────────────────────────────────────────────
def test_bridge_tools():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "agentpi_bridge",
        PATCH + "/dish-chat/backend/app/tools/agentpi_bridge.py"
    )
    # Stub httpx so we don't need it installed
    import sys, types
    if "httpx" not in sys.modules:
        sys.modules["httpx"] = types.ModuleType("httpx")
    if "langchain" not in sys.modules:
        lc = types.ModuleType("langchain"); lc.tools = types.ModuleType("langchain.tools")
        def tool(name=None):
            def dec(fn): fn.name=name or fn.__name__; fn.description=fn.__doc__ or ""; return fn
            return dec
        lc.tools.tool = tool
        sys.modules["langchain"] = lc
        sys.modules["langchain.tools"] = lc.tools

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    new_tools = ["agentpi_mqtt_start", "agentpi_mqtt_stop",
                 "agentpi_homeassistant_start", "agentpi_homeassistant_stop",
                 "agentpi_clear_inventory"]
    for name in new_tools:
        t = getattr(mod, name)
        assert t.name,        f"{name} has no .name"
        assert t.description, f"{name} has no .description"

check("PATCH-04 5 new bridge tools importable with name+description", test_bridge_tools)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-05: constants + truncation marker in source
# ─────────────────────────────────────────────────────────────────────────────
def test_patch05():
    src = pathlib.Path(PATCH + "/dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py").read_text()
    assert "SCRATCHPAD_LIMIT = 8_000" in src,   "SCRATCHPAD_LIMIT constant missing"
    assert "SUMMARIZER_LIMIT = 16_000" in src,  "SUMMARIZER_LIMIT constant missing"
    assert "TRUNCATED" in src,                  "[TRUNCATED] marker missing"
    assert "SCRATCHPAD_LIMIT" in src,           "SCRATCHPAD_LIMIT not used"

check("PATCH-05 named constants + truncation marker", test_patch05)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-06: both _llm_type values in set
# ─────────────────────────────────────────────────────────────────────────────
def test_patch06():
    src = pathlib.Path(PATCH + "/dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py").read_text()
    assert '"coverity-assist"' in src,                "base type missing"
    assert '"coverity-assist-tool-enabled"' in src,   "tool-enabled type missing"
    # Both should appear inside the same set literal
    m = re.search(r'_COVERITY_LLM_TYPES\s*=\s*\{([^}]+)\}', src)
    assert m, "_COVERITY_LLM_TYPES set not found"
    body = m.group(1)
    assert "coverity-assist" in body and "coverity-assist-tool-enabled" in body

check("PATCH-06 _COVERITY_LLM_TYPES set contains both values", test_patch06)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-02: mDNS fast-path demotion
# ─────────────────────────────────────────────────────────────────────────────
def test_patch02():
    src = pathlib.Path(PATCH + "/dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py").read_text()
    assert "_is_mdns_specific" in src, "_is_mdns_specific() not injected"
    assert "PATCH-02" in src,          "PATCH-02 comment missing"
    assert "agentpi_discover_devices" in src, "bridge guard missing in fast-path"
    # Functional check via exec
    ns: dict = {}
    exec(re.search(r'def _is_mdns_specific.*?(?=\ndef )', src, re.S).group(0), ns)
    fn = ns["_is_mdns_specific"]
    assert     fn("discover using mDNS only"),   "mDNS not detected"
    assert     fn("find .local devices"),        ".local not detected"
    assert not fn("list devices using arp"),     "ARP flagged as mDNS"

check("PATCH-02 _is_mdns_specific + fast-path demotion", test_patch02)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-03: _search_harder short-circuit + fallback
# ─────────────────────────────────────────────────────────────────────────────
def test_patch03():
    src = pathlib.Path(PATCH + "/dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py").read_text()
    assert "fallback_tool" in src,   "fallback_tool param missing"
    assert "network_dead" in src,    "network_dead short-circuit missing"
    assert "short-circuiting" in src or "short-circuit" in src, "short-circuit comment missing"

check("PATCH-03 _search_harder fallback_tool + short-circuit in source", test_patch03)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-06 on coverity_assist_chat_model.py
# ─────────────────────────────────────────────────────────────────────────────
def test_patch06_model():
    src = pathlib.Path(PATCH + "/dish-chat/backend/app/core/llm/coverity_assist_chat_model.py").read_text()
    assert "_llm_type_base" in src, "_llm_type_base alias missing"
    assert 'return "coverity-assist"' in src, "base return value missing"

check("PATCH-06 coverity_assist_chat_model _llm_type_base alias", test_patch06_model)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-08: SQLite store (pure-Python, no models import needed)
# ─────────────────────────────────────────────────────────────────────────────
def test_patch08():
    src = pathlib.Path(PATCH + "/backend/store.py").read_text()
    assert "sqlite3" in src,          "sqlite3 import missing"
    assert "WAL" in src,              "WAL journal mode missing"
    assert "DeviceInventory" in src,  "DeviceInventory class missing"
    assert "upsert_many" in src,      "upsert_many missing"
    assert "AGENTPI_DB" in src,       "AGENTPI_DB env var missing"

check("PATCH-08 SQLite store structure", test_patch08)

# ─────────────────────────────────────────────────────────────────────────────
# Result summary
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 56)
print(f"  RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
print("=" * 56)
if FAIL:
    raise SystemExit(1)
print("ALL TESTS PASS")
