"""
Extract the getpaid citation subgraph to static CSVs.

Run once locally to refresh `public/data/nodes.csv` + `public/data/edges.csv`,
which the marimo notebook reads at runtime (WASM-safe — no live DuckDB).

Strategy:
  - 25 curated seeds (canonical_ffm_seeds.csv) form the labeled trunk.
  - Pull each seed's incoming citations (papers that cite it) and outgoing
    references (papers it cites) from the portfolio DuckDB.
  - Cap the extension layer at the top-K most-cited papers across the trunk.
  - Tag Banister lineage on nodes whose parent_doi chain reaches Banister 1975
    or Calvert 1976.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

# The seeds list and the literature-index DuckDB live outside this repo, so
# they are passed in (--seeds / --db, or CN_SEEDS_CSV / CN_DB_PATH) rather than
# resolved from a hardcoded relative layout that breaks when the repo moves.
OUT_DIR = Path(__file__).resolve().parent / "public" / "data"

BANISTER_ANCHORS = {"manual:banister1975", "10.1109/tsmc.1976.5409179"}

# Hardcoded fallback titles for canonical FFM founding papers that aren't
# in the getpaid paper_metadata table. Verify against original publications.
FALLBACK_META = {
    "manual:banister1975": {
        "title": "A systems model of training for athletic performance",
        "authors": "Banister EW; Calvert TW; Savage MV; Bach T",
        "venue": "Australian Journal of Sports Medicine 7:57-61",
    },
    "10.1109/tsmc.1976.5409179": {
        "title": "A systems model of the effects of training on physical performance",
        "authors": "Calvert TW; Banister EW; Savage MV; Bach T",
        "venue": "IEEE Transactions on Systems, Man, and Cybernetics SMC-6(2):94-102",
    },
    "10.1152/jappl.1991.71.5.2044": {
        "title": "Adequacy of a systems structure in the modeling of training effects on performance",
        "authors": "Busso T; Carasso C; Lacour JR",
        "venue": "Journal of Applied Physiology 71(5):2044-2049",
    },
    "10.1152/jappl.1991.71.3.1151": {
        "title": "Optimizing athletic performance by influence curves",
        "authors": "Fitz-Clarke JR; Morton RH; Banister EW",
        "venue": "Journal of Applied Physiology 71(3):1151-1158",
    },
    "10.1007/978-1-4615-5887-3_43": {
        "title": "Clinical Dose-Response Effects of Exercise",
        "authors": "Banister EW; Morton RH; Fitz-Clarke JR",
        "venue": "The Physiology and Pathophysiology of Exercise Tolerance (Springer, 1996), pp. 297-309",
    },
    "10.1249/mss.0b013e318207c15d": {
        "title": "Exercise dosing to retain resistance training adaptations in young and older adults",
        "authors": "Bickel CS; Cross JM; Bamman MM",
        "venue": "Medicine & Science in Sports & Exercise 43(7):1177-1187",
    },
}

FAMILY_RANK = {
    "classical": 1,
    "variable_dose": 2,
    "perpot": 3,
    "rt_specific": 4,
    "statistical_critique": 5,
    "bayesian_hier": 6,
    "review": 7,
    "extended": 8,
    "uncategorized": 9,
}


def norm_doi(s: str) -> str:
    if s is None:
        return ""
    s = s.strip()
    if s.lower().startswith("http"):
        s = s.split("doi.org/", 1)[-1]
    if s.startswith(("manual:", "openalex:", "srxiv:")):
        return s
    return s.lower()


def load_seeds(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            row["doi"] = norm_doi(row["doi"])
            row["parent_doi"] = norm_doi(row.get("parent_doi", ""))
            row["year"] = int(row["year"]) if row.get("year") else None
            rows.append(row)
    return rows


def banister_lineage(seeds: list[dict]) -> set[str]:
    """DOIs reachable from Banister anchors via parent_doi chains."""
    by_parent: dict[str, list[str]] = defaultdict(list)
    for s in seeds:
        if s["parent_doi"]:
            by_parent[s["parent_doi"]].append(s["doi"])

    reached = set(BANISTER_ANCHORS)
    frontier = list(BANISTER_ANCHORS)
    while frontier:
        nxt = []
        for p in frontier:
            for child in by_parent.get(p, []):
                if child not in reached:
                    reached.add(child)
                    nxt.append(child)
        frontier = nxt
    return reached


def fetch_extension(con: duckdb.DuckDBPyConnection, seed_dois: list[str], top_k: int) -> list[dict]:
    """Top-K papers in the getpaid candidate pool that cite OR are cited by trunk."""
    real_dois = [d for d in seed_dois if not d.startswith("manual:")]
    if not real_dois:
        return []
    q = f"""
    WITH seeds AS (SELECT UNNEST(?::VARCHAR[]) AS doi),
    forward AS (
        SELECT c.citing_doi AS doi, c.cited_doi AS seed_doi
        FROM cites c JOIN seeds s ON s.doi = c.cited_doi
        WHERE c.source_project = 'getpaid'
    ),
    backward AS (
        SELECT c.cited_doi AS doi, c.citing_doi AS seed_doi
        FROM cites c JOIN seeds s ON s.doi = c.citing_doi
        WHERE c.source_project = 'getpaid'
    ),
    combined AS (SELECT * FROM forward UNION ALL SELECT * FROM backward),
    scored AS (
        SELECT
            combined.doi,
            COUNT(DISTINCT combined.seed_doi) AS n_seed_links,
            MAX(cand.citing_cited_by) AS cite_count
        FROM combined
        LEFT JOIN candidates cand
            ON cand.doi = combined.doi AND cand.source_project = 'getpaid'
        WHERE combined.doi NOT IN (SELECT doi FROM seeds)
        GROUP BY combined.doi
    )
    SELECT
        s.doi,
        s.n_seed_links,
        s.cite_count,
        p.year, p.lastname, p.title, p.venue, p.authors
    FROM scored s
    LEFT JOIN paper_metadata p ON p.doi = s.doi
    WHERE p.year IS NOT NULL
    ORDER BY s.n_seed_links DESC, COALESCE(s.cite_count, 0) DESC
    LIMIT {int(top_k)}
    """
    rows = con.execute(q, [real_dois]).fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


def compute_extension_families(
    con: duckdb.DuckDBPyConnection,
    extension_dois: list[str],
    seed_doi_to_family: dict[str, str],
) -> dict[str, str]:
    """For each extension DOI, find the dominant family of seed papers it links to.

    Counts cite-edges (in either direction) between the extension and each seed,
    groups by the seed's curated family, and returns the family with the most
    links. Ties broken by sum of citation counts.
    """
    real_ext = [d for d in extension_dois if not d.startswith("manual:")]
    real_seeds = [d for d in seed_doi_to_family if not d.startswith("manual:")]
    if not real_ext or not real_seeds:
        return {}

    q = """
    WITH ext AS (SELECT UNNEST(?::VARCHAR[]) AS doi),
    seeds AS (SELECT UNNEST(?::VARCHAR[]) AS doi),
    links AS (
        SELECT c.citing_doi AS ext_doi, c.cited_doi AS seed_doi
        FROM cites c
        WHERE c.source_project = 'getpaid'
          AND c.citing_doi IN (SELECT doi FROM ext)
          AND c.cited_doi  IN (SELECT doi FROM seeds)
        UNION ALL
        SELECT c.cited_doi AS ext_doi, c.citing_doi AS seed_doi
        FROM cites c
        WHERE c.source_project = 'getpaid'
          AND c.cited_doi  IN (SELECT doi FROM ext)
          AND c.citing_doi IN (SELECT doi FROM seeds)
    )
    SELECT ext_doi, seed_doi FROM links
    """
    rows = con.execute(q, [real_ext, real_seeds]).fetchall()

    # ext_doi → family → count
    tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ext_doi, seed_doi in rows:
        fam = seed_doi_to_family.get(seed_doi)
        if fam and fam != "uncategorized":
            tally[ext_doi][fam] += 1

    return {
        ext: max(fams.items(), key=lambda kv: kv[1])[0]
        for ext, fams in tally.items() if fams
    }


def fetch_seed_citation_counts(
    con: duckdb.DuckDBPyConnection, seed_dois: list[str]
) -> dict[str, int]:
    real_dois = [d for d in seed_dois if not d.startswith("manual:")]
    if not real_dois:
        return {}
    q = """
    SELECT doi, MAX(citing_cited_by) AS cite_count
    FROM candidates
    WHERE doi IN (SELECT UNNEST(?::VARCHAR[])) AND source_project='getpaid'
    GROUP BY doi
    """
    out = {}
    for doi, cnt in con.execute(q, [real_dois]).fetchall():
        if cnt is not None:
            out[doi] = int(cnt)
    return out


def fetch_seed_metadata(
    con: duckdb.DuckDBPyConnection, seed_dois: list[str]
) -> dict[str, dict]:
    """Look up real title / authors / venue for seed DOIs from paper_metadata."""
    real_dois = [d for d in seed_dois if not d.startswith("manual:")]
    if not real_dois:
        return {}
    q = """
    SELECT doi, title, authors, venue
    FROM paper_metadata
    WHERE doi IN (SELECT UNNEST(?::VARCHAR[]))
    """
    out = {}
    for doi, title, authors, venue in con.execute(q, [real_dois]).fetchall():
        out[doi] = {
            "title": title or "",
            "authors": authors or "",
            "venue": venue or "",
        }
    return out


def fetch_subgraph_edges(
    con: duckdb.DuckDBPyConnection, node_dois: list[str]
) -> list[tuple[str, str, str]]:
    real_dois = [d for d in node_dois if not d.startswith("manual:")]
    if not real_dois:
        return []
    q = """
    SELECT DISTINCT citing_doi, cited_doi, source_pipeline
    FROM cites
    WHERE source_project = 'getpaid'
      AND citing_doi IN (SELECT UNNEST(?::VARCHAR[]))
      AND cited_doi  IN (SELECT UNNEST(?::VARCHAR[]))
    """
    return [(r[0], r[1], r[2]) for r in con.execute(q, [real_dois, real_dois]).fetchall()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=150,
                    help="extension nodes (most-linked to trunk) to include")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--seeds", type=Path, default=os.environ.get("CN_SEEDS_CSV"),
                    help="canonical_ffm_seeds.csv (default: $CN_SEEDS_CSV)")
    ap.add_argument("--db", type=Path, default=os.environ.get("CN_DB_PATH"),
                    help="literature-index DuckDB, opened read-only (default: $CN_DB_PATH)")
    args = ap.parse_args(argv)
    for flag, env, path in (("--seeds", "CN_SEEDS_CSV", args.seeds), ("--db", "CN_DB_PATH", args.db)):
        if path is None:
            ap.error(f"{flag} is required (or set {env})")
        if not path.exists():
            ap.error(f"{flag}: no such file: {path}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[extract] DB: {args.db}")
    print(f"[extract] seeds: {args.seeds}")
    print(f"[extract] out: {args.out_dir}")

    seeds = load_seeds(args.seeds)
    print(f"[extract] {len(seeds)} curated seeds")

    lineage = banister_lineage(seeds)
    print(f"[extract] {len(lineage)} nodes in Banister lineage (via parent_doi chains)")

    con = duckdb.connect(str(args.db), read_only=True)

    seed_dois = [s["doi"] for s in seeds]
    seed_cites = fetch_seed_citation_counts(con, seed_dois)
    seed_meta = fetch_seed_metadata(con, seed_dois)
    _meta_hits = sum(1 for s in seeds if seed_meta.get(s["doi"], {}).get("title"))
    print(f"[extract] seed metadata: {_meta_hits}/{len(seeds)} resolved from paper_metadata")

    extension = fetch_extension(con, seed_dois, args.top_k)
    print(f"[extract] {len(extension)} extension nodes (top-{args.top_k} linkage)")

    seed_doi_to_family = {s["doi"]: (s["family"] or "uncategorized") for s in seeds}
    ext_dois = [norm_doi(e["doi"]) for e in extension]
    ext_family_map = compute_extension_families(con, ext_dois, seed_doi_to_family)

    nodes = []
    for s in seeds:
        cites = int(s["citation_count_override"]) if s.get("citation_count_override") else \
                seed_cites.get(s["doi"], 0)
        # Resolution order for title/authors/venue:
        # 1. paper_metadata (DB) — preferred, comes from CrossRef enrichment
        # 2. FALLBACK_META — hardcoded for canonical papers not in DB
        # 3. label / empty — last resort
        meta = seed_meta.get(s["doi"]) or FALLBACK_META.get(s["doi"], {})
        nodes.append({
            "doi": s["doi"],
            "year": s["year"],
            "label": s["label"],
            "family": s["family"] or "uncategorized",
            "extension_family": "",
            "paradigm": s["paradigm"] or "unknown",
            "citation_count": cites,
            "is_seed": True,
            "is_banister_lineage": s["doi"] in lineage,
            "title": meta.get("title") or s["label"],
            "authors": meta.get("authors") or "",
            "venue": meta.get("venue") or "",
            "family_rank": FAMILY_RANK.get(s["family"] or "uncategorized", 9),
        })

    for ext in extension:
        doi = norm_doi(ext["doi"])
        title = ext.get("title") or ""
        authors = ext.get("authors") or ""
        last = ext.get("lastname") or (authors.split(";")[0].strip() if authors else "")
        year = ext.get("year")
        short = f"{last} {year}" if last and year else (last or doi)[:40]
        nodes.append({
            "doi": doi,
            "year": int(year) if year else None,
            "label": short,
            "family": "extended",
            "extension_family": ext_family_map.get(doi, ""),
            "paradigm": "unknown",
            "citation_count": int(ext.get("cite_count") or 0),
            "is_seed": False,
            "is_banister_lineage": False,
            "title": title,
            "authors": authors,
            "venue": ext.get("venue") or "",
            "family_rank": FAMILY_RANK["extended"],
        })

    node_dois = [n["doi"] for n in nodes]
    auto_edges = fetch_subgraph_edges(con, node_dois)
    print(f"[extract] {len(auto_edges)} citation edges from DuckDB (subgraph)")

    manual_edges = []
    for s in seeds:
        if s["parent_doi"]:
            manual_edges.append((s["doi"], s["parent_doi"], "manual"))
    print(f"[extract] {len(manual_edges)} manual lineage edges from seeds")

    # Manual lineage edges go first so they win the dedup below. When the index
    # also records the same citation, the pair must stay "manual"; with auto
    # edges first, a more complete index silently erased lineage links.
    edge_set = set()
    edges = []
    for src, dst, kind in manual_edges + list(auto_edges):
        key = (src, dst)
        if key in edge_set or src == dst:
            continue
        edge_set.add(key)
        edges.append({"source": src, "target": dst, "kind": kind})

    nodes_with_edges = {e["source"] for e in edges} | {e["target"] for e in edges}
    seeds_set = {s["doi"] for s in seeds}
    keep = nodes_with_edges | seeds_set
    nodes = [n for n in nodes if n["doi"] in keep]
    print(f"[extract] final: {len(nodes)} nodes, {len(edges)} edges")

    nodes_path = args.out_dir / "nodes.csv"
    edges_path = args.out_dir / "edges.csv"
    with nodes_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(nodes[0].keys()))
        w.writeheader()
        w.writerows(nodes)
    with edges_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "target", "kind"])
        w.writeheader()
        w.writerows(edges)
    print(f"[extract] wrote {nodes_path} ({nodes_path.stat().st_size} bytes)")
    print(f"[extract] wrote {edges_path} ({edges_path.stat().st_size} bytes)")


if __name__ == "__main__":
    sys.exit(main())
