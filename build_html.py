"""Build the citation-network HTML from nodes/edges CSVs.

Pure-Python builder: reads the static CSVs, emits a self-contained HTML
fragment using vis-network from a CDN. The fragment is what the marimo
notebook embeds via mo.iframe(...). Running this standalone lets us smoke-
test the visualization without spinning up marimo at all.

Usage:
    python build_html.py                 # writes dist/standalone.html
    python build_html.py --out foo.html  # writes foo.html
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "public" / "data"
VENDOR_JS_PATH = HERE / "public" / "vendor" / "vis-network-9.1.9.min.js"

# Okabe-Ito (Wong 2011), CVD-safe on the #0E1117 canvas, plus a distinct
# vis-network shape per family so identity never rests on color alone.
# Keep in sync with notebook.py and render_static.py.
FAMILY_COLOR = {
    "classical":            "#E69F00",
    "variable_dose":        "#56B4E9",
    "other":                "#CC79A7",
    "statistical_critique": "#D55E00",
    "bayesian_hier":        "#F0E442",
    "review":               "#009E73",
}
FAMILY_SHAPE = {
    "classical": "dot", "variable_dose": "square", "other": "triangleDown",
    "statistical_critique": "triangle", "bayesian_hier": "diamond", "review": "hexagon",
}
# One-node families share the "Other models" slot (Okabe-Ito has 6 dark-safe hues).
FAMILY_GROUP = {"perpot": "other", "rt_specific": "other"}
FALLBACK_COLOR = "#999999"
ANCHOR_DOIS = {"manual:banister1975", "10.1109/tsmc.1976.5409179"}
LINEAGE = "#FFFFFF"


def to_bool(s: str) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes", "t")


def load_nodes(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        try:
            year = int(r["year"]) if r["year"] else None
        except ValueError:
            year = None
        try:
            cites = int(r["citation_count"]) if r["citation_count"] else 0
        except ValueError:
            cites = 0
        is_seed = to_bool(r["is_seed"])
        # effective family: for extensions, use the inferred extension_family
        ext_fam = (r.get("extension_family") or "").strip()
        effective_fam = r["family"] if is_seed else (ext_fam or "extended")
        effective_fam = FAMILY_GROUP.get(effective_fam, effective_fam)
        out.append({
            "id": r["doi"],
            "label": r["label"] if (is_seed or r["doi"] in ANCHOR_DOIS) else "",
            "title_attr": _hover_title(r, cites, effective_fam),
            "year": year,
            "family": r["family"] or "uncategorized",
            "effective_family": effective_fam,
            "cites": cites,
            "is_seed": is_seed,
            "is_lineage": to_bool(r["is_banister_lineage"]),
            "is_anchor": r["doi"] in ANCHOR_DOIS,
            "doi": r["doi"],
            "_title": r.get("title") or "",
            "_authors": r.get("authors") or "",
            "_venue": r.get("venue") or "",
        })
    return out


def _hex_to_rgba(hex_str: str, alpha: float) -> str:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _hover_title(r: dict, cites: int, effective_fam: str) -> str:
    label = (r.get("label") or "").strip()
    title = (r.get("title") or "").strip()
    authors = (r.get("authors") or "")[:160].strip()
    venue = (r.get("venue") or "").strip()
    year = r.get("year") or ""
    fam = effective_fam or (r.get("family") or "")

    # Lead with title (preferred); fall back to label.
    heading = title if title else label
    sub = label if (title and label and title != label) else ""

    bits = []
    if heading:
        bits.append(f"<div style='font-size:13px;font-weight:600;line-height:1.35;margin-bottom:4px'>"
                    f"{_html_escape(heading[:180])}</div>")
    if sub:
        bits.append(f"<div style='color:#aab2c4;font-size:11px;margin-bottom:4px'>{_html_escape(sub)}</div>")
    if authors:
        bits.append(f"<div style='font-size:11px;margin-bottom:2px'>{_html_escape(authors)}</div>")
    venue_year = " · ".join(x for x in [venue, str(year) if year else ""] if x)
    if venue_year:
        bits.append(f"<div style='font-size:11px;color:#9aa3b8;margin-bottom:4px'>{_html_escape(venue_year)}</div>")
    bits.append(
        f"<div style='font-size:11px;color:#9aa3b8'>"
        f"<span style='color:#E8E8EA'>{cites:,}</span> citations"
        f" · family: <span style='color:#E8E8EA'>{_html_escape(fam)}</span></div>"
    )
    if to_bool(r.get("is_banister_lineage", "")):
        bits.append("<div style='color:#FFFFFF;font-size:11px;margin-top:4px'><b>★ Banister lineage</b></div>")
    return "".join(bits)


def _html_escape(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&#39;")
    )


def load_edges(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def style_node(n: dict) -> dict:
    fam = n["effective_family"]
    base_hex = FAMILY_COLOR.get(fam, FALLBACK_COLOR)
    cites = n["cites"]
    size = 10 + 22 * (math.log10(cites + 1) / math.log10(2000 + 1))
    if n["is_anchor"]:
        size += 12
    elif n["is_seed"]:
        size += 4

    if n["is_seed"]:
        fill = base_hex
        # Lineage = white ring; other seeds ring in their own color so white stays unique.
        border_color = LINEAGE if n["is_lineage"] else base_hex
        border_width = 4 if n["is_anchor"] else (3 if n["is_lineage"] else 1.6)
    else:
        # extension node: muted family color (low-saturation fill, subtle border)
        fill = _hex_to_rgba(base_hex, 0.45)
        border_color = _hex_to_rgba(base_hex, 0.7)
        border_width = 0.8

    shape = "star" if n["is_anchor"] else FAMILY_SHAPE.get(fam, "dot")

    return {
        "id": n["id"],
        "label": n["label"],
        "title": n["title_attr"],
        "year": n["year"],
        "is_anchor": n["is_anchor"],
        "shape": shape,
        "size": round(size, 1),
        "color": {
            "background": fill,
            "border": border_color,
            "highlight": {"background": base_hex, "border": LINEAGE},
            "hover":     {"background": base_hex, "border": LINEAGE},
        },
        "borderWidth": border_width,
        "borderWidthSelected": border_width + 1,
        "font": {"color": "#E8E8EA", "size": 12, "face": "Inter, system-ui, sans-serif",
                 "strokeWidth": 0, "background": "rgba(14,17,23,0.7)"},
    }


FAMILY_LABEL = [
    ("classical", "Classical"), ("variable_dose", "Variable dose"), ("other", "Other models"),
    ("statistical_critique", "Statistical critique"), ("bayesian_hier", "Bayesian"), ("review", "Review"),
]
_GLYPH = {  # 12x12 SVG marks matching the vis-network node shapes
    "dot": '<circle cx="6" cy="6" r="5"/>',
    "square": '<rect x="1" y="1" width="10" height="10"/>',
    "triangle": '<polygon points="6,1 11,11 1,11"/>',
    "triangleDown": '<polygon points="1,1 11,1 6,11"/>',
    "diamond": '<polygon points="6,0.5 11.5,6 6,11.5 0.5,6"/>',
    "hexagon": '<polygon points="3,1 9,1 12,6 9,11 3,11 0,6"/>',
}


def legend_html() -> str:
    """Legend rows: shape + color + name, so the key never relies on color alone."""
    rows = [
        f'<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="{FAMILY_COLOR[k]}">'
        f'{_GLYPH[FAMILY_SHAPE[k]]}</svg>{name}</div>'
        for k, name in FAMILY_LABEL
    ]
    rows.append('<div><svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" '
                'fill="none" stroke="#FFFFFF" stroke-width="2"/></svg>Banister lineage</div>')
    rows.append('<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#FFFFFF"><polygon '
                'points="6,0.5 7.5,4.5 11.5,4.6 8.3,7.1 9.4,11.2 6,8.8 2.6,11.2 3.7,7.1 0.5,4.6 4.5,4.5"/>'
                '</svg>Founding equations (Banister 1975, Calvert 1976)</div>')
    return "\n  ".join(rows)


def style_edge(e: dict) -> dict:
    if e["kind"] == "manual":
        return {
            "from": e["source"], "to": e["target"],
            "color": {"color": "rgba(255,255,255,0.7)", "highlight": LINEAGE},
            "width": 1.6, "smooth": {"type": "continuous"},
        }
    return {
        "from": e["source"], "to": e["target"],
        "color": {"color": "rgba(180,180,200,0.18)", "highlight": "rgba(255,255,255,0.6)"},
        "width": 0.6, "smooth": {"type": "continuous"},
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>The Banister Constellation</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #0E1117; color: #E8E8EA;
               font-family: Inter, system-ui, -apple-system, sans-serif; height: 100%; overflow: hidden; }}
  #net {{ width: 100vw; height: 100vh; position: relative; z-index: 2; }}
  #legend {{
    position: fixed; top: 12px; left: 12px; z-index: 10;
    background: rgba(20,24,33,0.85); border: 1px solid #2a2f3d; border-radius: 8px;
    padding: 10px 12px; font-size: 12px; line-height: 1.55; max-width: 260px;
  }}
  #legend h4 {{ margin: 0 0 6px 0; font-size: 13px; font-weight: 600; }}
  #legend svg {{ width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; }}
  #legend .hint {{ margin-top: 6px; color: #aab2c4; font-size: 11px; }}
  #legend .hint-touch {{ display: none; }}
  @media (hover: none) {{
    #legend .hint-mouse {{ display: none; }}
    #legend .hint-touch {{ display: block; }}
  }}
  .controls {{ position: fixed; top: 12px; right: 12px; z-index: 10;
              background: rgba(20,24,33,0.85); border: 1px solid #2a2f3d; border-radius: 8px;
              padding: 8px 10px; font-size: 12px; }}
  .controls button {{ background: #1a1f2e; color: #E8E8EA; border: 1px solid #3a4156;
                      border-radius: 4px; padding: 4px 10px; cursor: pointer;
                      font-family: inherit; font-size: 12px; margin-right: 4px; }}
  .controls button:hover {{ border-color: #FFFFFF; }}
  /* Phones: buttons become a full-width row at the top; the legend stacks
     under them in two compact columns instead of colliding with them. */
  @media (max-width: 600px) {{
    .controls {{ left: 12px; right: 12px; display: flex; gap: 4px; padding: 6px; }}
    .controls button {{ flex: 1; margin: 0; padding: 6px 4px; min-height: 32px; }}
    #legend {{ top: 62px; right: 12px; max-width: none; padding: 8px 10px; font-size: 11px;
               line-height: 1.45; column-count: 2; column-gap: 12px; }}
    #legend h4 {{ column-span: all; }}
    #legend .hint {{ column-span: all; }}
  }}
  .vis-tooltip {{ background: #1a1f2e !important; color: #E8E8EA !important;
                 border: 1px solid #5a6377 !important; padding: 8px 10px !important;
                 font-family: inherit !important; font-size: 12px !important;
                 max-width: 380px !important; border-radius: 6px !important; }}
  #year-axis {{
    position: fixed; inset: 0;
    pointer-events: none; z-index: 1;
  }}
  #year-axis .gridline {{
    position: absolute; left: 0; right: 0; height: 1px;
    background: rgba(80,90,110,0.18);
  }}
  #year-axis .label {{
    position: absolute; left: 8px; transform: translateY(-50%);
    color: #aab2c4; font-size: 11px; font-family: inherit;
    background: rgba(14,17,23,0.7); padding: 1px 6px; border-radius: 3px;
  }}
</style>
</head>
<body>
<div id="legend">
  <h4>The Banister Constellation</h4>
  {legend_html}
  <div class="hint hint-mouse">Hover a paper for details. Drag to pan, scroll to zoom.</div>
  <div class="hint hint-touch">Best on a desktop. On touch: drag to pan, pinch to zoom.</div>
</div>
<div class="controls">
  <button onclick="lineageOnly()">Lineage only</button>
  <button onclick="lineageAll()">All papers</button>
  <button onclick="fit()">Fit view</button>
</div>
<div id="year-axis"></div>
<div id="net"></div>
<script>__VIS_NETWORK_JS__</script>
<script>
  const ALL_NODES_RAW = {nodes_json};
  const ALL_EDGES = {edges_json};
  const LINEAGE_IDS = new Set({lineage_ids_json});

  // Year-to-y mapping: pin each node's y by publication year, free x.
  // Older (1974) at top; newer (2026) at bottom; physics spreads x by force.
  const YEAR_MIN = 1974, YEAR_MAX = 2026;
  const SPAN_PX = 2400;  // total vertical extent in vis-network canvas units
  function yearToY(y) {{
    if (y == null) y = (YEAR_MIN + YEAR_MAX) / 2;
    return ((y - YEAR_MIN) / (YEAR_MAX - YEAR_MIN)) * SPAN_PX - SPAN_PX / 2;
  }}

  // Build display-ready nodes: pin y, convert title to DOM (so HTML renders),
  // add small initial x for force-stabilization spread.
  const ALL_NODES = ALL_NODES_RAW.map(n => {{
    const node = Object.assign({{}}, n);
    if (typeof node.title === "string") {{
      const el = document.createElement("div");
      el.innerHTML = node.title;
      node.title = el;
    }}
    node.y = yearToY(node.year);
    node.x = (Math.random() - 0.5) * 900;
    node.fixed = {{ x: false, y: true }};
    return node;
  }});

  const nodesDS = new vis.DataSet(ALL_NODES);
  const edgesDS = new vis.DataSet(ALL_EDGES);

  const options = {{
    nodes: {{ shape: "dot", scaling: {{ min: 10, max: 40 }} }},
    edges: {{
      arrows: {{ to: {{ enabled: false }} }},
      smooth: {{ type: "continuous", roundness: 0.2 }},
      hoverWidth: 0.5,
    }},
    physics: {{
      enabled: true,
      solver: "forceAtlas2Based",
      forceAtlas2Based: {{
        gravitationalConstant: -120,
        centralGravity: 0.005,
        springLength: 60,
        springConstant: 0.05,
        damping: 0.6,
        avoidOverlap: 0.7,
      }},
      stabilization: {{ enabled: true, iterations: 400, fit: true }},
      minVelocity: 0.5,
    }},
    interaction: {{
      hover: true, tooltipDelay: 80, dragNodes: true, dragView: true,
      zoomView: true, multiselect: false, navigationButtons: false,
    }},
    layout: {{ improvedLayout: false }},
  }};

  const container = document.getElementById("net");
  const network = new vis.Network(container, {{ nodes: nodesDS, edges: edgesDS }}, options);

  network.once("stabilizationIterationsDone", () => {{
    network.setOptions({{ physics: {{ enabled: false }} }});
    network.fit({{ animation: {{ duration: 400 }} }});
  }});

  // Year axis: draw decade gridlines + labels aligned to node y positions.
  function drawYearAxis() {{
    const axis = document.getElementById("year-axis");
    axis.querySelectorAll(".gridline, .label").forEach(t => t.remove());
    const ticks = [1975, 1985, 1995, 2005, 2015, 2025];
    ticks.forEach(yr => {{
      const canvasY = yearToY(yr);
      const pt = network.canvasToDOM({{ x: 0, y: canvasY }});
      const line = document.createElement("div");
      line.className = "gridline";
      line.style.top = pt.y + "px";
      axis.appendChild(line);
      const lbl = document.createElement("div");
      lbl.className = "label";
      lbl.textContent = yr;
      lbl.style.top = pt.y + "px";
      axis.appendChild(lbl);
    }});
  }}

  network.on("afterDrawing", drawYearAxis);
  window.addEventListener("resize", drawYearAxis);

  function withReheat(fn) {{
    fn();
    network.setOptions({{ physics: {{ enabled: true }} }});
    network.once("stabilizationIterationsDone", () => {{
      network.setOptions({{ physics: {{ enabled: false }} }});
      network.fit({{ animation: {{ duration: 400 }} }});
    }});
  }}

  function lineageOnly() {{
    withReheat(() => {{
      nodesDS.clear(); edgesDS.clear();
      nodesDS.add(ALL_NODES.filter(n => LINEAGE_IDS.has(n.id)));
      edgesDS.add(ALL_EDGES.filter(e => LINEAGE_IDS.has(e.from) && LINEAGE_IDS.has(e.to)));
    }});
  }}
  function lineageAll() {{
    withReheat(() => {{
      nodesDS.clear(); edgesDS.clear();
      nodesDS.add(ALL_NODES); edgesDS.add(ALL_EDGES);
    }});
  }}
  function fit() {{ network.fit({{ animation: {{ duration: 400 }} }}); }}
</script>
</body>
</html>
"""


def build(out_path: Path) -> None:
    nodes_raw = load_nodes(DATA_DIR / "nodes.csv")
    edges_raw = load_edges(DATA_DIR / "edges.csv")

    node_ids = {n["id"] for n in nodes_raw}
    edges_valid = [e for e in edges_raw if e["source"] in node_ids and e["target"] in node_ids]

    vis_nodes = [style_node(n) for n in nodes_raw]
    vis_edges = [style_edge(e) for e in edges_valid]
    lineage_ids = [n["id"] for n in nodes_raw if n["is_lineage"]]

    def _safe_json(obj):
        # Harden against </script> injection if any string field contains the literal.
        return json.dumps(obj).replace("</", "<\\/")

    if not VENDOR_JS_PATH.exists():
        raise FileNotFoundError(
            f"Missing vendored vis-network at {VENDOR_JS_PATH}. "
            f"Download with:\n  mkdir -p {VENDOR_JS_PATH.parent}\n"
            f"  curl -sSL -o {VENDOR_JS_PATH} "
            f"https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"
        )
    vis_network_js = VENDOR_JS_PATH.read_text(encoding="utf-8")

    html = HTML_TEMPLATE.format(
        legend_html=legend_html(),
        nodes_json=_safe_json(vis_nodes),
        edges_json=_safe_json(vis_edges),
        lineage_ids_json=_safe_json(lineage_ids),
    ).replace("__VIS_NETWORK_JS__", vis_network_js)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"  {len(vis_nodes)} nodes, {len(vis_edges)} edges, {len(lineage_ids)} in lineage")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "dist" / "standalone.html")
    args = ap.parse_args()
    build(args.out)
