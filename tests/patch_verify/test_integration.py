"""
AgentPi patch integration tests.
Discovers repo root from its own file location — works on any machine.
Run from repo root: python3 tests/patch_verify/test_integration.py
"""
import sys, os, pathlib, re

# Repo root = two directories above this file (tests/patch_verify/test_integration.py)
REPO = str(pathlib.Path(__file__).resolve().parents[2])
sys.path.insert(0, os.path.join(REPO, "dish-chat", "backend"))
sys.path.insert(1, os.path.join(REPO, "backend"))

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

check("PATCH-01+07 host_context self-identity + 60s TTL cache", test_host_context)

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

check("PATCH-04 5 new bridge tools importable with name + description", test_bridge_tools)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-04: registry has >=23 tools including all 5 new
# ─────────────────────────────────────────────────────────────────────────────
def test_registry_count():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/tools/registry.py")).read_text()
    m = re.search(r'"agent_mode":\s*lambda:\s*\[(.*?)\]', src, re.S)
    assert m, "agent_mode lambda not found"
    names = re.findall(r'\b(agentpi_\w+|agent_\w+)\b', m.group(1))
    assert len(names) >= 23, f"{len(names)} tools (want >=23)"
    new = {"agentpi_mqtt_start","agentpi_mqtt_stop","agentpi_homeassistant_start",
           "agentpi_homeassistant_stop","agentpi_clear_inventory"}
    missing = new - set(names)
    assert not missing, f"Missing: {missing}"

check("PATCH-04 registry: 23 tools, all 5 new present", test_registry_count)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-05: named constants + truncation marker
# ─────────────────────────────────────────────────────────────────────────────
def test_patch05():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text()
    assert "SCRATCHPAD_LIMIT = 8_000"  in src, "SCRATCHPAD_LIMIT missing"
    assert "SUMMARIZER_LIMIT = 16_000" in src, "SUMMARIZER_LIMIT missing"
    assert "TRUNCATED"                 in src, "[TRUNCATED] marker missing"

check("PATCH-05 named constants + truncation marker", test_patch05)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-06: _COVERITY_LLM_TYPES set contains both type strings
# ─────────────────────────────────────────────────────────────────────────────
def test_patch06():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text()
    m = re.search(r'_COVERITY_LLM_TYPES\s*=\s*\{([^}]+)\}', src)
    assert m, "_COVERITY_LLM_TYPES set not found"
    body = m.group(1)
    assert "coverity-assist-tool-enabled" in body, "tool-enabled missing"
    assert 'coverity-assist"' in body,             "base type missing"

check("PATCH-06 _COVERITY_LLM_TYPES both values", test_patch06)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-02: _is_mdns_specific + network fast-path guard
# ─────────────────────────────────────────────────────────────────────────────
def test_patch02():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text()
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

check("PATCH-02 _is_mdns_specific + fast-path demotion", test_patch02)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-03: _search_harder short-circuit + fallback_tool
# ─────────────────────────────────────────────────────────────────────────────
def test_patch03():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py")).read_text()
    assert "fallback_tool"    in src, "fallback_tool param missing"
    assert "network_dead"     in src, "network_dead flag missing"
    assert "short-circuiting" in src, "short-circuit log missing"

check("PATCH-03 _search_harder fallback + short-circuit", test_patch03)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-06: coverity_assist_chat_model _llm_type_base alias
# ─────────────────────────────────────────────────────────────────────────────
def test_patch06_model():
    src = pathlib.Path(os.path.join(REPO,
        "dish-chat/backend/app/core/llm/coverity_assist_chat_model.py")).read_text()
    assert "_llm_type_base"           in src, "_llm_type_base missing"
    assert 'return "coverity-assist"' in src, "base return value missing"
    assert "PATCH-06"                 in src, "PATCH-06 comment missing"

check("PATCH-06 coverity_assist_chat_model _llm_type_base alias", test_patch06_model)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH-08: SQLite store structure
# ─────────────────────────────────────────────────────────────────────────────
def test_patch08():
    src = pathlib.Path(os.path.join(REPO, "backend/store.py")).read_text()
    assert "sqlite3"         in src, "sqlite3 import missing"
    assert "WAL"             in src, "WAL journal mode missing"
    assert "DeviceInventory" in src, "DeviceInventory class missing"
    assert "upsert_many"     in src, "upsert_many missing"
    assert "AGENTPI_DB"      in src, "AGENTPI_DB env var missing"

check("PATCH-08 SQLite store structure", test_patch08)

# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 56)
print(f"  RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
print("=" * 56)
if FAIL:
    raise SystemExit(1)
print("ALL TESTS PASS")
