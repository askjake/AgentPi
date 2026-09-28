from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Optional

from langchain.tools import tool


GENEALOGY_IDENTITY_CONTRACT = "agentpi-genealogy-identity-v1"
_MAX_GEDCOM_BYTES = 50_000_000
_MAX_ARCHIVE_BYTES = 100_000_000
_MAX_CANDIDATES = 20


def _workspace(chat_id: str) -> Path:
    if not chat_id or not str(chat_id).strip():
        raise ValueError("chat_id is required")
    base = Path(os.environ.get("AGENT_MODE_WORKDIR", "/tmp/home_agent")).resolve()
    ws = (base / str(chat_id)).resolve()
    if ws != base and base not in ws.parents:
        raise ValueError("workspace escaped AGENT_MODE_WORKDIR")
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _inside_workspace(ws: Path, path: Path) -> bool:
    resolved = path.resolve()
    return resolved == ws or ws in resolved.parents


def _zip_gedcom_members(path: Path) -> list[zipfile.ZipInfo]:
    if path.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"Archive is too large for bounded genealogy inspection: {path.stat().st_size} bytes"
        )
    with zipfile.ZipFile(path) as archive:
        return [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".ged")
        ]


def _resolve_gedcom_path(chat_id: str, gedcom_path: str = "") -> Path:
    ws = _workspace(chat_id)
    if gedcom_path and str(gedcom_path).strip():
        candidate = Path(str(gedcom_path).strip())
        if not candidate.is_absolute():
            candidate = ws / candidate
        resolved = candidate.resolve()
        if not _inside_workspace(ws, resolved):
            raise ValueError("GEDCOM path must stay inside the conversation workspace")
        if not resolved.is_file():
            raise FileNotFoundError(f"GEDCOM source not found: {resolved}")
    else:
        ged_matches: list[Path] = []
        for p in ws.rglob("*.ged"):
            if not p.is_file() or ".git" in p.parts or ".venv" in p.parts:
                continue
            resolved_candidate = p.resolve()
            if _inside_workspace(ws, resolved_candidate):
                ged_matches.append(resolved_candidate)
        ged_matches = sorted(dict.fromkeys(ged_matches))

        if len(ged_matches) == 1:
            resolved = ged_matches[0]
        elif len(ged_matches) > 1:
            rel = [str(p.relative_to(ws)) for p in ged_matches[:10]]
            raise ValueError(
                "Multiple GEDCOM files found; pass gedcom_path explicitly: "
                + ", ".join(rel)
            )
        else:
            zip_matches: list[Path] = []
            for p in ws.rglob("*.zip"):
                if not p.is_file() or ".git" in p.parts or ".venv" in p.parts:
                    continue
                resolved_candidate = p.resolve()
                if not _inside_workspace(ws, resolved_candidate):
                    continue
                try:
                    members = _zip_gedcom_members(resolved_candidate)
                except (OSError, zipfile.BadZipFile, ValueError):
                    continue
                if members:
                    zip_matches.append(resolved_candidate)
            zip_matches = sorted(dict.fromkeys(zip_matches))
            if not zip_matches:
                raise FileNotFoundError(
                    "No .ged file or ZIP containing a GEDCOM was found in the conversation workspace"
                )
            if len(zip_matches) > 1:
                rel = [str(p.relative_to(ws)) for p in zip_matches[:10]]
                raise ValueError(
                    "Multiple archives contain GEDCOM files; pass gedcom_path explicitly: "
                    + ", ".join(rel)
                )
            resolved = zip_matches[0]

    if resolved.suffix.lower() not in {".ged", ".zip"}:
        raise ValueError("genealogy identity checks require a .ged file or ZIP containing a GEDCOM")
    return resolved


def _read_gedcom_source(chat_id: str, gedcom_path: str = "") -> tuple[str, str]:
    ws = _workspace(chat_id)
    path = _resolve_gedcom_path(chat_id, gedcom_path)
    if path.suffix.lower() == ".ged":
        size = path.stat().st_size
        if size > _MAX_GEDCOM_BYTES:
            raise ValueError(
                f"GEDCOM file is too large for bounded identity inspection: {size} bytes"
            )
        return str(path.relative_to(ws)), path.read_text(encoding="utf-8", errors="replace")

    members = _zip_gedcom_members(path)
    if not members:
        raise FileNotFoundError("ZIP does not contain a GEDCOM file")
    if len(members) > 1:
        names = [info.filename for info in members[:10]]
        raise ValueError(
            "ZIP contains multiple GEDCOM files; extract/select one explicitly: "
            + ", ".join(names)
        )
    info = members[0]
    if info.file_size > _MAX_GEDCOM_BYTES:
        raise ValueError(
            f"GEDCOM member is too large for bounded identity inspection: {info.file_size} bytes"
        )
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(info)
    label = f"{path.relative_to(ws)}!{info.filename}"
    return label, raw.decode("utf-8", errors="replace")


def _record_blocks(text: str) -> list[str]:
    return [
        block.strip()
        for block in re.split(r"(?m)(?=^0 (?:@[^\r\n]+@ )?(?:INDI|FAM)\s*$)", text)
        if block.strip().startswith("0 ")
    ]


def _record_id(block: str) -> str | None:
    match = re.match(r"0 (@[^\s]+@) (?:INDI|FAM)\s*$", block.splitlines()[0].strip())
    return match.group(1) if match else None


def _tag_value(block: str, level: int, tag: str) -> str | None:
    match = re.search(
        rf"(?m)^{level} {re.escape(tag)}(?:\s+(.+))?$",
        block,
    )
    if not match:
        return None
    value = (match.group(1) or "").strip()
    return value or None


def _event_value(block: str, tag: str, subtag: str) -> str | None:
    lines = block.splitlines()
    inside = False
    for line in lines:
        if line.startswith(f"1 {tag}"):
            inside = True
            continue
        if inside and line.startswith("1 "):
            break
        if inside and line.startswith(f"2 {subtag} "):
            return line[len(f"2 {subtag} "):].strip() or None
    return None


def _year(value: str | None) -> int | None:
    if not value:
        return None
    years = re.findall(r"(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)", value)
    return int(years[-1]) if years else None


def _clean_name(value: str | None) -> str:
    text = str(value or "").replace("/", " ")
    return " ".join(text.split())


def _name_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _clean_name(value).casefold())


def _name_match(target: str, candidate: str) -> tuple[str, list[str]]:
    target_tokens = _name_tokens(target)
    candidate_tokens = _name_tokens(candidate)
    if not target_tokens or not candidate_tokens:
        return "none", ["name missing"]

    if target_tokens == candidate_tokens:
        return "exact", []

    target_surname = target_tokens[-1]
    candidate_surname = candidate_tokens[-1]
    if target_surname != candidate_surname:
        return "none", [f"surname differs: {candidate_surname} != {target_surname}"]

    if target_tokens[0] != candidate_tokens[0]:
        return "none", [f"given name differs: {candidate_tokens[0]} != {target_tokens[0]}"]

    missing = [token for token in target_tokens[1:-1] if token not in candidate_tokens[1:-1]]
    reasons = []
    if missing:
        reasons.append("target name token(s) absent from candidate: " + ", ".join(missing))
    return "partial", reasons


def _individual(block: str) -> dict[str, Any]:
    rid = _record_id(block)
    return {
        "id": rid,
        "name": _clean_name(_tag_value(block, 1, "NAME")),
        "sex": _tag_value(block, 1, "SEX"),
        "birth_date": _event_value(block, "BIRT", "DATE"),
        "birth_year": _year(_event_value(block, "BIRT", "DATE")),
        "birth_place": _event_value(block, "BIRT", "PLAC"),
        "death_date": _event_value(block, "DEAT", "DATE"),
        "death_year": _year(_event_value(block, "DEAT", "DATE")),
        "death_place": _event_value(block, "DEAT", "PLAC"),
        "famc": re.findall(r"(?m)^1 FAMC (@[^\s]+@)\s*$", block),
        "fams": re.findall(r"(?m)^1 FAMS (@[^\s]+@)\s*$", block),
    }


def _family(block: str) -> dict[str, Any]:
    return {
        "id": _record_id(block),
        "husb": _tag_value(block, 1, "HUSB"),
        "wife": _tag_value(block, 1, "WIFE"),
        "children": re.findall(r"(?m)^1 CHIL (@[^\s]+@)\s*$", block),
        "marriage_date": _event_value(block, "MARR", "DATE"),
        "marriage_place": _event_value(block, "MARR", "PLAC"),
    }


def _person_ref(individuals: dict[str, dict[str, Any]], rid: str | None) -> dict[str, Any] | None:
    if not rid or rid not in individuals:
        return None
    person = individuals[rid]
    return {
        "id": person["id"],
        "name": person["name"],
        "birth_year": person["birth_year"],
        "death_year": person["death_year"],
    }


def _family_context(
    candidate: dict[str, Any],
    individuals: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    parents: list[dict[str, Any]] = []
    spouses: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []

    for fid in candidate.get("famc", []):
        fam = families.get(fid)
        if not fam:
            continue
        for rid in (fam.get("husb"), fam.get("wife")):
            ref = _person_ref(individuals, rid)
            if ref and ref["id"] != candidate["id"]:
                parents.append(ref)

    for fid in candidate.get("fams", []):
        fam = families.get(fid)
        if not fam:
            continue
        for rid in (fam.get("husb"), fam.get("wife")):
            ref = _person_ref(individuals, rid)
            if ref and ref["id"] != candidate["id"]:
                spouses.append(ref)
        for rid in fam.get("children", []):
            ref = _person_ref(individuals, rid)
            if ref:
                children.append(ref)

    def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out = []
        for item in items:
            rid = str(item.get("id") or "")
            if rid and rid not in seen:
                seen.add(rid)
                out.append(item)
        return out

    return {
        "parents": dedupe(parents),
        "spouses": dedupe(spouses),
        "children": dedupe(children),
    }


def _ancestor_context(
    candidate: dict[str, Any],
    individuals: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
    max_depth: int,
) -> list[dict[str, Any]]:
    depth_limit = max(0, min(int(max_depth), 8))
    if depth_limit == 0:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = {str(candidate.get("id") or "")}
    queue: list[tuple[str, int, str]] = []

    for fid in candidate.get("famc", []):
        fam = families.get(fid)
        if not fam:
            continue
        for rid in (fam.get("husb"), fam.get("wife")):
            if rid:
                queue.append((rid, 1, str(candidate.get("id") or "")))

    while queue:
        rid, generation, child_id = queue.pop(0)
        if not rid or rid in seen or generation > depth_limit:
            continue
        seen.add(rid)
        person = individuals.get(rid)
        if not person:
            continue
        out.append({
            "id": person["id"],
            "name": person["name"],
            "birth_year": person["birth_year"],
            "death_year": person["death_year"],
            "generation": generation,
            "child_id": child_id,
        })
        for fid in person.get("famc", []):
            fam = families.get(fid)
            if not fam:
                continue
            for parent_id in (fam.get("husb"), fam.get("wife")):
                if parent_id:
                    queue.append((parent_id, generation + 1, rid))
    return out


def inspect_gedcom_identity(
    *,
    chat_id: str,
    target_name: str,
    gedcom_path: str = "",
    expected_birth_year: Optional[int] = None,
    expected_death_year: Optional[int] = None,
    ancestor_depth: int = 4,
) -> dict[str, Any]:
    source_label, text = _read_gedcom_source(chat_id, gedcom_path)

    individuals: dict[str, dict[str, Any]] = {}
    families: dict[str, dict[str, Any]] = {}
    for block in _record_blocks(text):
        first = block.splitlines()[0]
        rid = _record_id(block)
        if not rid:
            continue
        if first.endswith(" INDI"):
            individuals[rid] = _individual(block)
        elif first.endswith(" FAM"):
            families[rid] = _family(block)

    candidates: list[dict[str, Any]] = []
    for person in individuals.values():
        name_match, reasons = _name_match(target_name, person["name"])
        if name_match == "none":
            continue

        conflicts = list(reasons)
        if expected_birth_year is not None:
            if person.get("birth_year") is None:
                conflicts.append(f"birth year missing; expected {int(expected_birth_year)}")
            elif int(person["birth_year"]) != int(expected_birth_year):
                conflicts.append(
                    f"birth year differs: {person['birth_year']} != {int(expected_birth_year)}"
                )
        if expected_death_year is not None:
            if person.get("death_year") is None:
                conflicts.append(f"death year missing; expected {int(expected_death_year)}")
            elif int(person["death_year"]) != int(expected_death_year):
                conflicts.append(
                    f"death year differs: {person['death_year']} != {int(expected_death_year)}"
                )

        candidate = dict(person)
        candidate["name_match"] = name_match
        candidate["conflicts"] = conflicts
        candidate["family"] = _family_context(person, individuals, families)
        candidate["ancestors"] = _ancestor_context(
            person,
            individuals,
            families,
            ancestor_depth,
        )
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item["name_match"] != "exact",
            bool(item["conflicts"]),
            item.get("birth_year") or 9999,
            item.get("name") or "",
        )
    )
    candidates = candidates[:_MAX_CANDIDATES]

    exact_clean = [c for c in candidates if c["name_match"] == "exact" and not c["conflicts"]]
    partial_clean = [c for c in candidates if c["name_match"] == "partial" and not c["conflicts"]]

    if not candidates:
        status = "not_found"
    elif len(exact_clean) == 1:
        status = "match"
    elif len(exact_clean) > 1 or partial_clean:
        status = "ambiguous"
    else:
        status = "conflict"

    return {
        "contract": GENEALOGY_IDENTITY_CONTRACT,
        "status": status,
        "target": {
            "name": _clean_name(target_name),
            "expected_birth_year": expected_birth_year,
            "expected_death_year": expected_death_year,
            "ancestor_depth": max(0, min(int(ancestor_depth), 8)),
        },
        "gedcom_path": source_label,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "continuity_rule": (
            "Only status=match permits treating a GEDCOM candidate as the target person. "
            "For ambiguous/conflict/not_found, keep identities separate and state what evidence is missing."
        ),
    }


@tool("agent_genealogy_identity_check")
def agent_genealogy_identity_check(
    chat_id: str,
    target_name: str,
    gedcom_path: str = "",
    expected_birth_year: Optional[int] = None,
    expected_death_year: Optional[int] = None,
    ancestor_depth: int = 4,
) -> str:
    """Resolve a named person against a workspace GEDCOM without merging identities.

    Use before concluding that a same/similar-name GEDCOM record is the person
    under research. Partial names, conflicting dates, or multiple candidates
    remain ambiguous/conflicting. This tool is read-only.
    """
    try:
        result = inspect_gedcom_identity(
            chat_id=chat_id,
            target_name=target_name,
            gedcom_path=gedcom_path,
            expected_birth_year=expected_birth_year,
            expected_death_year=expected_death_year,
            ancestor_depth=ancestor_depth,
        )
    except Exception as exc:
        result = {
            "contract": GENEALOGY_IDENTITY_CONTRACT,
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "continuity_rule": "No genealogy identity conclusion is permitted from this failed check.",
        }
    return json.dumps(result, indent=2)
