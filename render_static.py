"""Static PNG renderer for the FFM citation network.

Reads the same nodes.csv / edges.csv that the interactive viz uses and
renders the constellation as static PNGs for the portfolio hero, the
homepage tile, and the social cards.

Layout: y is pinned to publication year (1975 at the top). x comes from a
spring layout, then each 5-year band is rank-spread across a width that
grows with the band's paper count, so the sparse early decades stay a
narrow trunk and the graph widens as the field grows. A greedy pass keeps
nodes from overlapping.

Encoding: Okabe-Ito color plus a marker shape per family (never color
alone); the Banister lineage is a white ring, white links and a soft halo.

Usage:
    python render_static.py
    # -> dist_static/citation_network.png               (1600x1200, hero)
    # -> dist_static/citation_network_tile.png          (1600x900, 16:9 tile)
    # -> dist_static/citation_network_card.png          (1200x630, social)
    # -> dist_static/citation_network_card_labeled.png  (1200x630, lineage labels)
"""
from __future__ import annotations

import csv
import io
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
from adjustText import adjust_text  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "public" / "data"
OUT = HERE / "dist_static"
DPI = 100

BG = "#0E1117"
FG = "#E8E8EA"
LABEL_INK = "#C9CED8"
MUTED = "#9AA3B8"
GRID = "#5A6377"
LINEAGE = "#FFFFFF"

# Okabe-Ito (Wong 2011), CVD-safe on the dark canvas. Every family also gets
# its own marker shape, so identity never rests on color alone.
FAMILY_COLOR = {
    "classical":            "#E69F00",
    "variable_dose":        "#56B4E9",
    "other":                "#CC79A7",
    "statistical_critique": "#D55E00",
    "bayesian_hier":        "#F0E442",
    "review":               "#009E73",
}
FAMILY_MARKER = {
    "classical": "o", "variable_dose": "s", "other": "v",
    "statistical_critique": "^", "bayesian_hier": "D", "review": "h",
}
FAMILY_NAME = {
    "classical": "Classical", "variable_dose": "Variable dose", "other": "Other models",
    "statistical_critique": "Statistical critique", "bayesian_hier": "Bayesian", "review": "Review",
}
# One-node families share the "Other models" slot (Okabe-Ito has 6 dark-safe hues).
FAMILY_GROUP = {"perpot": "other", "rt_specific": "other"}
FAMILY_ORDER = ["classical", "variable_dose", "other", "statistical_critique", "bayesian_hier", "review"]

ANCHOR_DOIS = {"manual:banister1975", "10.1109/tsmc.1976.5409179"}
YEAR_MIN, YEAR_MAX = 1974, 2026

# Output canvases in px. top = title + legend strip, left = year labels.
SPECS = {
    "hero": dict(W=1600, H=1200, left=78, right=28, top=150, bottom=34, title=22, sub=12,
                 legend=9.8, year=10, label=9.5, size_k=1.0, chrome=True),
    "tile": dict(W=1600, H=900, left=96, right=24, top=40, bottom=20, title=0, sub=0,
                 legend=0, year=20, label=24, size_k=1.25, chrome=False),
    "card": dict(W=1200, H=630, left=64, right=20, top=118, bottom=18, title=24, sub=12.5,
                 legend=10.2, year=10.5, label=10, size_k=0.8, chrome=True),
}


def _to_bool(s: str) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes", "t")


def _short_label(lbl: str) -> str:
    """Display-only cleanup: 'J. Borresen 2009' -> 'Borresen 2009'; keeps 'Thomas & Busso 2008'."""
    toks = lbl.split()
    if "&" in toks or len(toks) <= 2 or not toks[-1].isdigit():
        return lbl
    return f"{toks[-2]} {toks[-1]}"


def load() -> tuple[list[dict], list[dict]]:
    with (DATA / "nodes.csv").open(encoding="utf-8") as f:
        nodes = list(csv.DictReader(f))
    with (DATA / "edges.csv").open(encoding="utf-8") as f:
        edges = list(csv.DictReader(f))
    for n in nodes:
        try:
            n["_year"] = int(n["year"]) if n["year"] else (YEAR_MIN + YEAR_MAX) // 2
        except ValueError:
            n["_year"] = (YEAR_MIN + YEAR_MAX) // 2
        try:
            n["_cites"] = int(n["citation_count"]) if n["citation_count"] else 0
        except ValueError:
            n["_cites"] = 0
        n["_is_seed"] = _to_bool(n["is_seed"])
        n["_is_lineage"] = _to_bool(n["is_banister_lineage"])
        n["_is_anchor"] = n["doi"] in ANCHOR_DOIS
        ext_fam = (n.get("extension_family") or "").strip()
        eff = n["family"] if n["_is_seed"] else (ext_fam or "extended")
        n["_effective_family"] = FAMILY_GROUP.get(eff, eff)
        n["_label"] = _short_label(n["label"])
    return nodes, edges


def _node_size(n: dict, k: float) -> float:
    """Marker area (pt^2), log-scaled by citations; lineage gets a floor since
    most founding papers carry no citation count in the index."""
    s = 60 + 220 * math.log10(n["_cites"] + 1) / math.log10(2001)
    if n["_is_anchor"]:
        s += 110
    elif n["_is_lineage"]:
        s = max(s + 30, 170)
    elif n["_is_seed"]:
        s += 24
    return s * k


def _radius_px(s: float) -> float:
    return 0.5 * math.sqrt(s) * DPI / 72


def _priority(n: dict):
    return (not n["_is_anchor"], not n["_is_lineage"], not n["_is_seed"], -n["_cites"], n["_year"])


def _year_y(yr: int, ah: float, pad: float) -> float:
    return pad + (ah - 2 * pad) * (1 - (yr - YEAR_MIN) / (YEAR_MAX - YEAR_MIN))


def compute_layout(nodes: list[dict], edges: list[dict], aw: float, ah: float,
                   pad: float = 14, seed: int = 7) -> dict:
    """Positions in axes pixels. y = year; x = spring layout, rank-spread per
    5-year band over a count-scaled width, then de-overlapped."""
    G = nx.Graph()
    G.add_nodes_from(n["doi"] for n in nodes)
    G.add_edges_from((e["source"], e["target"]) for e in edges
                     if e["source"] in G and e["target"] in G)
    rng = np.random.default_rng(seed)
    init = {n["doi"]: np.array([rng.uniform(-0.6, 0.6),
                                1 - (n["_year"] - YEAR_MIN) / (YEAR_MAX - YEAR_MIN)])
            for n in nodes}
    sp = nx.spring_layout(G, pos=init, k=0.85 / math.sqrt(max(len(G), 1)),
                          iterations=200, seed=seed)

    xs = np.array([sp[n["doi"]][0] for n in nodes])
    x_lo, x_hi = xs.min(), xs.max()
    bands: dict[int, list[dict]] = {}
    for n in nodes:
        bands.setdefault((n["_year"] - YEAR_MIN) // 5, []).append(n)
    pref = {}
    for members in bands.values():
        members.sort(key=lambda n: sp[n["doi"]][0])
        k = len(members)
        width = min(0.92, 0.12 + 0.03 * k) * aw
        center = 0.04 * aw + (np.mean([sp[n["doi"]][0] for n in members]) - x_lo) / (x_hi - x_lo) * 0.92 * aw
        center = aw / 2 + (center - aw / 2) * min(1.0, k / 30)  # sparse bands -> centered trunk
        left = min(max(center - width / 2, 0.04 * aw), 0.96 * aw - width)
        for i, n in enumerate(members):
            pref[n["doi"]] = left + ((i + 0.5) / k if k > 1 else 0.5) * width

    # Greedy de-overlap: each node takes the free x nearest its preferred x.
    pos, placed, gap = {}, [], 2.5
    for n in sorted(nodes, key=_priority):
        r, y = n["_r"], _year_y(n["_year"], ah, pad)
        best, best_ov = None, None
        for c in sorted(np.linspace(r + 1, aw - r - 1, 160), key=lambda c: abs(c - pref[n["doi"]])):
            ov = 0.0
            for (px, py, pr) in placed:
                need = r + pr + gap
                if abs(y - py) < need and abs(c - px) < need:
                    d = math.hypot(c - px, y - py)
                    if d < need:
                        ov += need - d
            if ov == 0:
                best = c
                break
            if best_ov is None or ov < best_ov:
                best, best_ov = c, ov
        placed.append((best, y, r))
        pos[n["doi"]] = (best, y)
    return pos


def _labeled(nodes: list[dict], mode: str) -> list[dict]:
    lineage = [n for n in nodes if n["_is_lineage"]]
    if mode == "lineage_top8":
        top = sorted([n for n in nodes if not n["_is_lineage"]], key=lambda n: -n["_cites"])[:8]
        return lineage + top
    if mode == "lineage":
        return lineage
    if mode == "anchor":
        return [n for n in nodes if n["doi"] == "manual:banister1975"]
    return []


def _rgb(hex_str: str) -> tuple[int, int, int]:
    return tuple(int(hex_str[i:i + 2], 16) for i in (1, 3, 5))


def _blend(hex_str: str, alpha: float) -> tuple[int, int, int]:
    return tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(_rgb(hex_str), _rgb(BG)))


def _reserved_colors() -> list[tuple[int, int, int]]:
    """Exact colors the palette must keep. Median cut alone drops the rare
    ones: in testing, the single Bayesian node's yellow merged into orange."""
    cols = [_rgb(h) for h in (BG, FG, LABEL_INK, MUTED, GRID, LINEAGE, *FAMILY_COLOR.values())]
    cols += [_blend(h, 0.72) for h in FAMILY_COLOR.values()]  # extension-node fills
    cols.append(_blend(LINEAGE, 0.16))                        # lineage halo
    return list(dict.fromkeys(cols))


def _save_png(fig, out_path: Path) -> None:
    """Save at the exact canvas size, then quantize to a 256-color palette:
    the reserved encoding colors plus median-cut colors for the rest, mapped
    without dithering so edges stay crisp. Flat colors on a dark canvas
    compress to well under half the size. Deterministic, so CI reproduces it."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=DPI)  # fixed canvas: exact pixel size
    buf.seek(0)
    with Image.open(buf) as im:
        rgb = im.convert("RGB")
    keep = _reserved_colors()
    n_free = 256 - len(keep)
    adaptive = rgb.quantize(colors=n_free, method=Image.Quantize.MEDIANCUT,
                            dither=Image.Dither.NONE).getpalette()[: 3 * n_free]
    palette = [v for c in keep for v in c] + adaptive
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(palette + [0] * (768 - len(palette)))
    rgb.quantize(palette=pal_img, dither=Image.Dither.NONE).save(out_path, format="PNG", optimize=True)


def render(out_path: Path, kind: str, labels: str) -> None:
    sp = SPECS[kind]
    W, H = sp["W"], sp["H"]
    nodes, edges = load()
    for n in nodes:
        n["_s"] = _node_size(n, sp["size_k"])
        n["_r"] = _radius_px(n["_s"])

    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=BG)
    aw, ah = W - sp["left"] - sp["right"], H - sp["top"] - sp["bottom"]
    ax = fig.add_axes([sp["left"] / W, sp["bottom"] / H, aw / W, ah / H])
    ax.set_xlim(0, aw)
    ax.set_ylim(0, ah)
    ax.axis("off")
    pad = 14
    pos = compute_layout(nodes, edges, aw, ah, pad)

    for yr in (1975, 1985, 1995, 2005, 2015, 2025):
        y = _year_y(yr, ah, pad)
        ax.axhline(y, color=GRID, lw=0.6, alpha=0.22, zorder=0.5)
        ax.text(-10, y, str(yr), color=MUTED, fontsize=sp["year"], ha="right", va="center", clip_on=False)

    auto, lineage = [], []
    for e in edges:
        if e["source"] in pos and e["target"] in pos:
            seg = [pos[e["source"]], pos[e["target"]]]
            (lineage if e["kind"] == "manual" else auto).append(seg)
    ax.add_collection(LineCollection(auto, colors=GRID, linewidths=0.45 * sp["size_k"], alpha=0.22, zorder=1))
    ax.add_collection(LineCollection(lineage, colors=LINEAGE, linewidths=1.9 * sp["size_k"], alpha=0.85, zorder=2))

    lin = [n for n in nodes if n["_is_lineage"]]
    ax.scatter([pos[n["doi"]][0] for n in lin], [pos[n["doi"]][1] for n in lin],
               s=[n["_s"] * (2.6 if n["_is_anchor"] else 2.0) for n in lin],
               c=LINEAGE, alpha=0.16, linewidths=0, zorder=3)

    for fam in FAMILY_ORDER:
        for tier in ("ext", "seed", "lin"):
            grp = [n for n in nodes if n["_effective_family"] == fam and not n["_is_anchor"] and
                   ("lin" if n["_is_lineage"] else "seed" if n["_is_seed"] else "ext") == tier]
            if not grp:
                continue
            ax.scatter([pos[n["doi"]][0] for n in grp], [pos[n["doi"]][1] for n in grp],
                       s=[n["_s"] for n in grp], c=FAMILY_COLOR[fam], marker=FAMILY_MARKER[fam],
                       alpha={"ext": 0.72, "seed": 1.0, "lin": 1.0}[tier],
                       edgecolors={"ext": BG, "seed": BG, "lin": LINEAGE}[tier],
                       linewidths={"ext": 0.8, "seed": 1.2, "lin": 2.2}[tier] * sp["size_k"],
                       zorder={"ext": 4, "seed": 5, "lin": 5.5}[tier])
    anchors = [n for n in nodes if n["_is_anchor"]]
    ax.scatter([pos[n["doi"]][0] for n in anchors], [pos[n["doi"]][1] for n in anchors],
               s=[n["_s"] * 1.5 for n in anchors], c=LINEAGE, marker="*", edgecolors=BG,
               linewidths=1.0, zorder=6)

    texts = []
    if labels == "anchor":
        # Tile: one big label, set left of the founding star so it can't sit on it.
        for n in _labeled(nodes, labels):
            x, y = pos[n["doi"]]
            ax.text(x - n["_r"] * 1.6 - 8, y, n["_label"], ha="right", va="center", fontsize=sp["label"],
                    color=FG, fontweight="bold", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.15", fc=BG, ec="none", alpha=0.78))
        labels = "none"
    for n in _labeled(nodes, labels):
        x, y = pos[n["doi"]]
        texts.append(ax.text(
            x, y + n["_r"] + 3, n["_label"], ha="center", va="bottom", fontsize=sp["label"],
            color=FG if n["_is_lineage"] else LABEL_INK,
            fontweight="bold" if n["_is_lineage"] else "normal", zorder=7,
            bbox=dict(boxstyle="round,pad=0.15", fc=BG, ec="none", alpha=0.78)))
    overlaps = 0
    if texts:
        # iter_lim, not time_lim: a time budget makes label placement depend on
        # how fast the machine is, so CI and local renders could differ.
        adjust_text(texts, x=[p[0] for p in pos.values()], y=[p[1] for p in pos.values()], ax=ax,
                    expand=(1.08, 1.25), ensure_inside_axes=True, iter_lim=1000,
                    arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6, alpha=0.8))
        rend = fig.canvas.get_renderer()
        boxes = [t.get_window_extent(rend) for t in texts]
        overlaps = sum(boxes[i].overlaps(boxes[j])
                       for i in range(len(boxes)) for j in range(i + 1, len(boxes)))

    if sp["chrome"]:
        fig.text(sp["left"] / W, 1 - 18 / H, "The Banister Constellation", ha="left", va="top",
                 fontsize=sp["title"], fontweight="bold", color=FG)
        fig.text(sp["left"] / W, 1 - (24 + sp["title"] * 1.5) / H,
                 f"{len(nodes)} papers, 50 years of fitness-fatigue model research. "
                 "Top = 1975, bottom = 2025.",
                 ha="left", va="top", fontsize=sp["sub"], color=MUTED)
        handles = [Line2D([], [], ls="", marker=FAMILY_MARKER[f], ms=8, mfc=FAMILY_COLOR[f], mec=BG,
                          label=FAMILY_NAME[f]) for f in FAMILY_ORDER]
        handles.append(Line2D([], [], color=LINEAGE, lw=2, marker="o", ms=8, mfc="none", mec=LINEAGE,
                              label="Banister lineage"))
        fig.legend(handles=handles, loc="upper left", ncol=len(handles), frameon=False,
                   bbox_to_anchor=(sp["left"] / W - 0.006, 1 - (sp["top"] - 34) / H),
                   fontsize=sp["legend"], labelcolor=FG, handletextpad=0.3, columnspacing=1.1)

    OUT.mkdir(parents=True, exist_ok=True)
    _save_png(fig, out_path)
    plt.close(fig)
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes; "
          f"{len(texts)} labels, {overlaps} label overlaps)")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    render(OUT / "citation_network.png", "hero", "lineage_top8")
    render(OUT / "citation_network_tile.png", "tile", "anchor")
    render(OUT / "citation_network_card.png", "card", "none")
    render(OUT / "citation_network_card_labeled.png", "card", "lineage")


if __name__ == "__main__":
    main()
