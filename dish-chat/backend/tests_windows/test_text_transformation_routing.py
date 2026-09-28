from __future__ import annotations

import asyncio
import json

from langchain_core.messages import HumanMessage

from app.agent.agents.coverity_tool_loop_token_limit import run_coverity_tool_loop
from app.agent.agents.tools.registry import get_tools_set


CAPTAIN_PROMPT = """rewrite this prompt with the captain Josiah Hulett in the placeholder
You are HOME AGENT, a comprehensive AI assistant and research partner.
SUBJECT: [INSERT CAPTAIN'S FULL NAME / IDENTIFIER HERE]
RESEARCH OBJECTIVES:
1. Identity & Background
- Family lineage, nationality, and early life
5. Legacy & Documentation
- Genealogical records if applicable
RESEARCH APPROACH:
- Use public_web_search to pull current sources
- Cross-reference multiple sources before stating facts
HOME AGENT will execute the research plan step by step using live web searches
"""


class FixtureModel:
    _llm_type = "fixture"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def ainvoke(self, messages, config=None):
        self.calls.append(messages[0].content)
        if not self.replies:
            raise AssertionError("unexpected extra planner call")
        return type("Reply", (), {"content": self.replies.pop(0)})()


def test_real_planner_keeps_captain_rewrite_template_inert(monkeypatch):
    tools = get_tools_set("search") + get_tools_set("agent_mode")
    dispatched = []

    def forbidden_sync(*args, **kwargs):
        dispatched.append(("sync", args, kwargs))
        raise AssertionError("rewrite/template content must not execute tools")

    async def forbidden_async(*args, **kwargs):
        dispatched.append(("async", args, kwargs))
        raise AssertionError("rewrite/template content must not execute tools")

    for tool in tools:
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        if name not in {"public_web_search", "agent_genealogy_identity_check"}:
            continue
        if getattr(tool, "func", None) is not None:
            monkeypatch.setattr(tool, "func", forbidden_sync)
        if getattr(tool, "coroutine", None) is not None:
            monkeypatch.setattr(tool, "coroutine", forbidden_async)

    model = FixtureModel([
        json.dumps({
            "action": "tool",
            "tool": "public_web_search",
            "input": "Captain Josiah Hulett",
        }),
        json.dumps({
            "action": "final",
            "final": (
                "You are HOME AGENT, a comprehensive AI assistant and research partner.\n"
                "SUBJECT: Captain Josiah Hulett\n"
                "Keep the original research objectives and replace the placeholder with Captain Josiah Hulett."
            ),
        }),
    ])

    answer = asyncio.run(run_coverity_tool_loop(
        model=model,
        tools=tools,
        messages=[
            HumanMessage(content="We were previously researching an ancestry GEDCOM family lineage."),
            HumanMessage(content=CAPTAIN_PROMPT),
        ],
        config={"configurable": {"thread_id": "captain-rewrite-live"}},
        max_steps=3,
    ))

    assert answer.content.startswith("You are HOME AGENT")
    assert "Captain Josiah Hulett" in answer.content
    assert dispatched == []
    assert len(model.calls) == 2
