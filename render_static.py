"""Static PNG renderer for the FFM citation network.

Reads the same nodes.csv / edges.csv that the interactive viz uses,
renders a static PNG matching the constellation aesthetic. Useful as a
portfolio thumbnail, social card, or teaser before the interactive ships.

Usage:
    python render_static.py
    # → writes dist_static/citation_network.png  (1600x1200, hero)
    # → writes dist_static/citation_network_card.png  (1200x630, social)
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "public" / "data"
OUT = HERE / "dist_static"

BG = "#0E1117"
FG = "#E8E8EA"
HALO_GOLD = "#FFC850"
EDGE_AUTO = "#5a6377"
EDGE_MANUAL = "#FFC850"

FAMILY_COLOR = {
    "classical":            "#E64B35",
    "variable_dose":        "#3C5488",
    "perpot":               "#4DBBD5",
    "rt_specific":          "#00A087",
    "statistical_critique": "#F39B7F",
    "bayesian_hier":        "#8491B4",
    "review":               "#B09C85",
    "extended":             "#7E6148",
    "uncategorized":        "#999999",
}
ANCHOR_DOIS = {"manual:banister1975", "10.1109/tsmc.1976.5409179"}
YEAR_MIN, YEAR_MAX = 1974, 2026


def _to_bool(s: str) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes", "t")


def load() -> tuple[list[dict], list[dict]]:
    with (DATA / "nodes.csv").open(encoding="utf-8") as f:
        nodes = list(csv.DictReader(f))
    with (DATA / "edges.csv").open(encoding="utf-8") as f:
        edges = list(csv.DictReader(f))
    for n in nodes:
        try:
            n["_year"] = int(n["year"]) if n["year"] else None
        except ValueError:
            n["_year"] = None
        try:
            n["_cites"] = int(n["citation_count"]) if n["citation_count"] else 0
        except ValueError:
            n["_cites"] = 0
        n["_is_seed"] = _to_bool(n["is_seed"])
        n["_is_lineage"] = _to_bool(n["is_banister_lineage"])
        n["_is_anchor"] = n["doi"] in ANCHOR_DOIS
        ext_fam = (n.get("extension_family") or "").strip()
        n["_effective_family"] = n["family"] if n["_is_seed"] else (ext_fam or "extended")
    return nodes, edges


def compute_layout(nodes: list[dict], edges: list[dict], width: float, height: float, seed: int = 7) -> dict:
    """y = pinned by year (older top, newer bottom); x = spring-layout spread."""
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["doi"])
    for e in edges:
        if e["source"] in G and e["target"] in G:
            G.add_edge(e["source"], e["target"])

    rng = np.random.default_rng(seed)
    init = {}
    for n in nodes:
        yr = n["_year"] if n["_year"] is not None else (YEAR_MIN + YEAR_MAX) // 2
        y_norm = (yr - YEAR_MIN) / (YEAR_MAX - YEAR_MIN)
        init[n["doi"]] = np.array([rng.uniform(-0.6, 0.6), 1.0 - y_norm], dtype=float)

    pos = nx.spring_layout(
        G, pos=init, k=0.85 / math.sqrt(max(len(G), 1)),
        iterations=200, seed=seed, weight=None,
    )
    for n in nodes:
        yr = n["_year"] if n["_year"] is not None else (YEAR_MIN + YEAR_MAX) // 2
        y_norm = (yr - YEAR_MIN) / (YEAR_MAX - YEAR_MIN)
        x, _ = pos[n["doi"]]
        pos[n["doi"]] = np.array([x * width, (1.0 - y_norm) * height])
    return pos


def render(out_path: Path, w_in: float, h_in: float, dpi: int,
           show_legend: bool = True, show_labels: bool = True,
           label_threshold: int | None = None) -> None:
    nodes, edges = load()
    width_units, height_units = w_in * dpi / 100, h_in * dpi / 100
    pos = compute_layout(nodes, edges, width=width_units * 0.75, height=height_units * 0.82)

    fig, ax = plt.subplots(figsize=(w_in, h_in), dpi=dpi, facecolor=BG)
    ax.set_facecolor(BG)

    edge_lookup = {n["doi"]: n for n in nodes}
    auto_segs, manual_segs = [], []
    for e in edges:
        if e["source"] not in edge_lookup or e["target"] not in edge_lookup:
            continue
        x0, y0 = pos[e["source"]]
        x1, y1 = pos[e["target"]]
        seg = [(x0, y0), (x1, y1)]
        if e["kind"] == "manual":
            manual_segs.append(seg)
        else:
            auto_segs.append(seg)

    from matplotlib.collections import LineCollection
    if auto_segs:
        ax.add_collection(LineCollection(auto_segs, colors=EDGE_AUTO,
                                          linewidths=0.4, alpha=0.32, zorder=1))
    if manual_segs:
        ax.add_collection(LineCollection(manual_segs, colors=EDGE_MANUAL,
                                          linewidths=1.6, alpha=0.7, zorder=2))

    halo_x, halo_y, halo_s = [], [], []
    for n in nodes:
        if not n["_is_lineage"]:
            continue
        x, y = pos[n["doi"]]
        halo_x.append(x); halo_y.append(y)
        base = 200 + 380 * math.log10(n["_cites"] + 1) / math.log10(2001)
        halo_s.append(base * (2.2 if n["_is_anchor"] else 1.6))
    if halo_x:
        ax.scatter(halo_x, halo_y, s=halo_s, c=HALO_GOLD, alpha=0.22,
                   linewidths=0, zorder=3)

    ext_xs, ext_ys, ext_colors, ext_sizes = [], [], [], []
    seed_xs, seed_ys, seed_colors, seed_sizes, seed_edges, seed_widths = [], [], [], [], [], []
    anchor_xs, anchor_ys = [], []
    for n in nodes:
        x, y = pos[n["doi"]]
        size_base = 60 + 220 * math.log10(n["_cites"] + 1) / math.log10(2001)
        if n["_is_anchor"]:
            size_base += 90
        elif n["_is_seed"]:
            size_base += 24
        color = FAMILY_COLOR.get(n["_effective_family"], "#999999")
        if n["_is_seed"]:
            seed_xs.append(x); seed_ys.append(y); seed_colors.append(color); seed_sizes.append(size_base)
            seed_edges.append(HALO_GOLD if n["_is_lineage"] else "#FFFFFF")
            seed_widths.append(2.4 if n["_is_anchor"] else (1.8 if n["_is_lineage"] else 1.0))
            if n["_is_anchor"]:
                anchor_xs.append(x); anchor_ys.append(y)
        else:
            ext_xs.append(x); ext_ys.append(y)
            ext_colors.append(color); ext_sizes.append(size_base)

    if ext_xs:
        ax.scatter(ext_xs, ext_ys, s=ext_sizes, c=ext_colors, alpha=0.55,
                   linewidths=0.4, edgecolors="#FFFFFF", zorder=4)
    if seed_xs:
        ax.scatter(seed_xs, seed_ys, s=seed_sizes, c=seed_colors,
                   linewidths=seed_widths, edgecolors=seed_edges, zorder=5)
    if anchor_xs:
        ax.scatter(anchor_xs, anchor_ys, s=300, c=HALO_GOLD, marker="*",
                   linewidths=1.2, edgecolors="#FFFFFF", zorder=6)

    if show_labels:
        for n in nodes:
            if not (n["_is_seed"] or n["_is_anchor"]):
                continue
            x, y = pos[n["doi"]]
            ax.annotate(
                n["label"], xy=(x, y), xytext=(0, 11), textcoords="offset points",
                ha="center", va="bottom", fontsize=8.5,
                color=FG if not n["_is_anchor"] else HALO_GOLD,
                fontweight="bold" if n["_is_anchor"] else "normal",
                zorder=7,
                bbox=dict(boxstyle="round,pad=0.18", facecolor=BG, edgecolor="none", alpha=0.7),
            )

    for yr in [1975, 1985, 1995, 2005, 2015, 2025]:
        y_pos = (1.0 - (yr - YEAR_MIN) / (YEAR_MAX - YEAR_MIN)) * height_units * 0.82
        ax.axhline(y=y_pos, color="#5a6377", linewidth=0.5, alpha=0.18, zorder=0)
        ax.text(-width_units * 0.405, y_pos, str(yr), color="#7a8499",
                fontsize=9, va="center", ha="right", zorder=8,
                bbox=dict(boxstyle="round,pad=0.2", facecolor=BG, edgecolor="none", alpha=0.6))

    ax.set_xlim(-width_units * 0.42, width_units * 0.42)
    ax.set_ylim(-height_units * 0.05, height_units * 0.87)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    if show_legend:
        legend_families = [
            ("classical", "Classical (Banister)"),
            ("variable_dose", "Variable dose (Busso)"),
            ("statistical_critique", "Statistical critique"),
            ("bayesian_hier", "Bayesian hierarchical"),
            ("review", "Review"),
            ("extended", "Extension"),
        ]
        handles = [
            mpatches.Patch(facecolor=FAMILY_COLOR[k], edgecolor="white", linewidth=0.4, label=v)
            for k, v in legend_families
        ]
        handles.append(mpatches.Patch(facecolor=HALO_GOLD, alpha=0.5,
                                      label="Banister lineage halo"))
        leg = ax.legend(handles=handles, loc="lower right", framealpha=0.85,
                        facecolor="#1a1f2e", edgecolor="#2a2f3d",
                        labelcolor=FG, fontsize=9.5,
                        title="The Banister Constellation",
                        title_fontsize=11, borderpad=0.8)
        leg.get_title().set_color(FG)
        leg.get_title().set_fontweight("bold")

    fig.text(0.5, 0.965, "The Banister Constellation",
             ha="center", va="top", fontsize=18, fontweight="bold", color=FG)
    fig.text(0.5, 0.935,
             "50 years of fitness-fatigue model literature, anchored on Banister 1975 + Calvert 1976",
             ha="center", va="top", fontsize=10.5, color="#9aa3b8")

    plt.subplots_adjust(left=0.05, right=0.97, top=0.92, bottom=0.03)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=BG, dpi=dpi, bbox_inches="tight",
                pad_inches=0.2)
    plt.close(fig)
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    render(OUT / "citation_network.png", w_in=16, h_in=12, dpi=120)
    render(OUT / "citation_network_card.png", w_in=12, h_in=6.3, dpi=120,
           show_legend=False, show_labels=False)
    render(OUT / "citation_network_card_labeled.png", w_in=12, h_in=6.3, dpi=120,
           show_legend=False, show_labels=True)


if __name__ == "__main__":
    main()
