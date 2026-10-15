"""Schema + invariant tests for the committed citation-network data.

These tests run against the static CSVs that ship in this repo. They do NOT
require the private DuckDB — they're the contract that the committed data
must satisfy at all times.

Run with:
    pytest tests/
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
NODES_CSV = HERE / "public" / "data" / "nodes.csv"
EDGES_CSV = HERE / "public" / "data" / "edges.csv"

ANCHOR_DOIS = {"manual:banister1975", "10.1109/tsmc.1976.5409179"}


def _load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_bool(s: str) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes", "t")


@pytest.fixture(scope="module")
def nodes() -> list[dict]:
    assert NODES_CSV.exists(), f"missing committed data: {NODES_CSV}"
    return _load_rows(NODES_CSV)


@pytest.fixture(scope="module")
def edges() -> list[dict]:
    assert EDGES_CSV.exists(), f"missing committed data: {EDGES_CSV}"
    return _load_rows(EDGES_CSV)


def test_no_duplicate_dois(nodes):
    seen, dupes = set(), []
    for n in nodes:
        if n["doi"] in seen:
            dupes.append(n["doi"])
        seen.add(n["doi"])
    assert not dupes, f"duplicate DOIs in nodes.csv: {dupes}"


def test_anchors_present(nodes):
    dois = {n["doi"] for n in nodes}
    missing = ANCHOR_DOIS - dois
    assert not missing, f"missing anchor DOIs: {missing}"


def test_anchors_marked_as_lineage(nodes):
    for n in nodes:
        if n["doi"] in ANCHOR_DOIS:
            assert _to_bool(n["is_seed"]), f"{n['doi']} is anchor but not is_seed"
            assert _to_bool(n["is_banister_lineage"]), (
                f"{n['doi']} is anchor but not is_banister_lineage"
            )


def test_all_seeds_have_titles(nodes):
    missing = []
    for n in nodes:
        if _to_bool(n["is_seed"]):
            title = (n.get("title") or "").strip()
            if not title:
                missing.append(n["doi"])
    assert not missing, f"seeds with empty title: {missing}"


def test_no_verify_title_placeholders(nodes):
    """Catch the FALLBACK_META placeholder pattern before it ships."""
    bad = [n["doi"] for n in nodes if "[verify" in (n.get("title") or "").lower()]
    assert not bad, f"placeholder titles still present: {bad}"


def test_all_edges_endpoint_in_nodes(nodes, edges):
    node_ids = {n["doi"] for n in nodes}
    orphan = []
    for e in edges:
        if e["source"] not in node_ids or e["target"] not in node_ids:
            orphan.append((e["source"], e["target"]))
    assert not orphan, f"edges with endpoints not in nodes: {orphan[:5]}"


def test_no_self_edges(edges):
    bad = [(e["source"], e["target"]) for e in edges if e["source"] == e["target"]]
    assert not bad, f"self-edges found: {bad}"


def test_every_lineage_paper_links_to_its_parent(nodes, edges):
    """Each lineage paper except the root (Banister 1975) has its curated
    parent_doi link drawn as a manual edge. Guards the extract.py dedup order:
    when citation edges won the dedup, a fuller index silently turned lineage
    links into ordinary citations and broke the chain."""
    has_parent_link = {e["source"] for e in edges if e["kind"] == "manual"}
    missing = [
        n["label"] for n in nodes
        if _to_bool(n["is_banister_lineage"]) and n["doi"] != "manual:banister1975"
        and n["doi"] not in has_parent_link
    ]
    assert not missing, f"lineage papers without a manual parent edge: {missing}"


def test_lineage_implies_seed(nodes):
    """is_banister_lineage=True is only set on curated seed papers — extensions
    are auto-discovered and not part of the curated trunk."""
    bad = [
        n["doi"] for n in nodes
        if _to_bool(n["is_banister_lineage"]) and not _to_bool(n["is_seed"])
    ]
    assert not bad, f"non-seed nodes marked as Banister lineage: {bad}"
