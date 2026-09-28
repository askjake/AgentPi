from __future__ import annotations

import asyncio
import json
import zipfile

from langchain_core.messages import HumanMessage

from app.agent.agents.coverity_tool_loop_token_limit import run_coverity_tool_loop
from app.agent.agents.tools.registry import get_tools_set


_GEDCOM = """0 HEAD
1 SOUR AgentPiFixture
0 @I1@ INDI
1 NAME Lillie /Griffith/
1 SEX F
1 BIRT
2 DATE 1 JAN 1876
2 PLAC Belmont, Garrard, Kentucky, USA
1 DEAT
2 DATE 22 OCT 1948
2 PLAC Stanford, Lincoln, Kentucky, USA
1 FAMS @F1@
0 @I2@ INDI
1 NAME Samuel C. /Montgomery/
1 SEX M
1 BIRT
2 DATE ABT 1872
1 FAMS @F1@
0 @F1@ FAM
1 HUSB @I2@
1 WIFE @I1@
1 MARR
2 DATE 1895
0 TRLR
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


def test_real_planner_blocks_lillie_identity_substitution_from_zipped_gedcom(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODE_WORKDIR", str(tmp_path))
    ws = tmp_path / "genealogy-chat" / "ancestry"
    ws.mkdir(parents=True)
    archive_path = ws / "Jacob Montgomery family tree.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Jacob Montgomery family tree.ged", _GEDCOM)

    model = FixtureModel([])

    answer = asyncio.run(run_coverity_tool_loop(
        model=model,
        tools=get_tools_set("agent_mode"),
        messages=[
            HumanMessage(content="We cloned an ancestry repo with a GEDCOM family tree."),
            HumanMessage(content="Target: Lillie Beatrice Griffith (1923-1989)."),
            HumanMessage(content="please deep dive into Lillie Beatrice Griffith"),
        ],
        config={"configurable": {"thread_id": "genealogy-chat"}},
        max_steps=3,
    ))

    assert answer.content.startswith("GENEALOGY_IDENTITY_CONTINUITY_CONFLICT")
    assert "Target: Lillie Beatrice Griffith" in answer.content
    assert "Lillie Griffith (b. 1876, d. 1948) [@I1@]" in answer.content
    assert "target name token(s) absent from candidate: beatrice" in answer.content
    assert "birth year differs: 1876 != 1923" in answer.content
    assert "death year differs: 1948 != 1989" in answer.content
    assert "No candidate was merged into the target identity." in answer.content
    assert model.calls == []



def test_real_planner_returns_lineage_unresolved_for_samuel_without_famc(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODE_WORKDIR", str(tmp_path))
    ws = tmp_path / "samuel-chat" / "ancestry"
    ws.mkdir(parents=True)
    archive_path = ws / "Jacob Montgomery family tree.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Jacob Montgomery family tree.ged", _GEDCOM)

    model = FixtureModel([])
    answer = asyncio.run(run_coverity_tool_loop(
        model=model,
        tools=get_tools_set("agent_mode"),
        messages=[
            HumanMessage(content="This is ancestry research using a GEDCOM family tree."),
            HumanMessage(
                content=(
                    "Separately investigate Samuel C. Montgomery and figure out whether he belongs "
                    "to the main Griffith branch or the main Montgomery branch."
                )
            ),
        ],
        config={"configurable": {"thread_id": "samuel-chat"}},
        max_steps=3,
    ))

    assert answer.content.startswith("GENEALOGY_LINEAGE_EVIDENCE_REQUIRED")
    assert "Identity matched: Samuel C. Montgomery [@I2@]" in answer.content
    assert "surname or spouse relationship is not proof of branch membership" in answer.content
    assert model.calls == []
