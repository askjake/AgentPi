from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.agent_mode import genealogy


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
1 FAMC @F1@
1 FAMS @F2@
0 @I2@ INDI
1 NAME George W. /Griffith/
1 SEX M
1 BIRT
2 DATE 1843
0 @I3@ INDI
1 NAME Mary E. /Crutcher/
1 SEX F
1 BIRT
2 DATE ABT 1845
0 @I4@ INDI
1 NAME Samuel C. /Montgomery/
1 SEX M
1 BIRT
2 DATE ABT 1872
1 FAMS @F2@
0 @I5@ INDI
1 NAME Lena /Montgomery/
1 SEX F
1 BIRT
2 DATE 1896
1 FAMC @F2@
0 @F1@ FAM
1 HUSB @I2@
1 WIFE @I3@
1 CHIL @I1@
1 MARR
2 DATE 1870
2 PLAC Garrard County, Kentucky, USA
0 @F2@ FAM
1 HUSB @I4@
1 WIFE @I1@
1 CHIL @I5@
1 MARR
2 DATE 1895
0 TRLR
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODE_WORKDIR", str(tmp_path))
    ws = tmp_path / "chat"
    tree_dir = ws / "ancestry" / "tree_extracted"
    tree_dir.mkdir(parents=True)
    ged = tree_dir / "Jacob Montgomery family tree.ged"
    ged.write_text(_GEDCOM, encoding="utf-8")
    return ws, ged


def test_lillie_beatrice_is_not_silently_replaced_by_lillie_griffith(workspace):
    _, ged = workspace
    report = genealogy.inspect_gedcom_identity(
        chat_id="chat",
        target_name="Lillie Beatrice Griffith",
        expected_birth_year=1923,
        expected_death_year=1989,
    )

    assert report["contract"] == "agentpi-genealogy-identity-v1"
    assert report["status"] == "conflict"
    assert report["gedcom_path"].endswith("Jacob Montgomery family tree.ged")
    assert report["candidate_count"] == 1

    candidate = report["candidates"][0]
    assert candidate["id"] == "@I1@"
    assert candidate["name"] == "Lillie Griffith"
    assert candidate["name_match"] == "partial"
    assert "target name token(s) absent from candidate: beatrice" in candidate["conflicts"]
    assert "birth year differs: 1876 != 1923" in candidate["conflicts"]
    assert "death year differs: 1948 != 1989" in candidate["conflicts"]

    assert candidate["family"]["parents"] == [
        {"id": "@I2@", "name": "George W. Griffith", "birth_year": 1843, "death_year": None},
        {"id": "@I3@", "name": "Mary E. Crutcher", "birth_year": 1845, "death_year": None},
    ]
    assert candidate["family"]["spouses"] == [
        {"id": "@I4@", "name": "Samuel C. Montgomery", "birth_year": 1872, "death_year": None}
    ]
    assert candidate["family"]["children"] == [
        {"id": "@I5@", "name": "Lena Montgomery", "birth_year": 1896, "death_year": None}
    ]


def test_exact_lillie_griffith_identity_can_match(workspace):
    report = genealogy.inspect_gedcom_identity(
        chat_id="chat",
        target_name="Lillie Griffith",
        expected_birth_year=1876,
        expected_death_year=1948,
    )

    assert report["status"] == "match"
    assert report["candidate_count"] == 1
    candidate = report["candidates"][0]
    assert candidate["name_match"] == "exact"
    assert candidate["conflicts"] == []


def test_partial_name_without_dates_stays_ambiguous(workspace):
    report = genealogy.inspect_gedcom_identity(
        chat_id="chat",
        target_name="Lillie Beatrice Griffith",
    )

    assert report["status"] == "conflict"
    assert report["candidates"][0]["name_match"] == "partial"
    assert report["candidates"][0]["conflicts"] == [
        "target name token(s) absent from candidate: beatrice"
    ]


def test_identity_tool_json_contract(workspace):
    tool = genealogy.agent_genealogy_identity_check
    fields = getattr(tool.args_schema, "model_fields", None) or getattr(tool.args_schema, "__fields__", {})
    assert "chat_id" in fields
    assert "target_name" in fields

    payload = json.loads(asyncio.run(tool.ainvoke({
        "chat_id": "chat",
        "target_name": "Lillie Griffith",
        "expected_birth_year": 1876,
        "expected_death_year": 1948,
    })))

    assert payload["contract"] == "agentpi-genealogy-identity-v1"
    assert payload["status"] == "match"


def test_genealogy_identity_tool_is_bound_in_agent_mode_registry(workspace):
    from app.agent.agents.tools.registry import get_tools_set

    names = {
        getattr(tool, "name", getattr(tool, "__name__", ""))
        for tool in get_tools_set("agent_mode")
    }
    assert "agent_genealogy_identity_check" in names


def test_gedcom_path_cannot_escape_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODE_WORKDIR", str(tmp_path / "runtime"))
    outside = tmp_path / "outside.ged"
    outside.write_text(_GEDCOM, encoding="utf-8")

    with pytest.raises(ValueError, match="must stay inside"):
        genealogy.inspect_gedcom_identity(
            chat_id="chat",
            target_name="Lillie Griffith",
            gedcom_path=str(outside),
        )
