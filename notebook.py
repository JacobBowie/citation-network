# Notebook-level marimo config: force the dark theme so the page matches the
# dark vis-network canvas. Without it the export defaults to "system", and a
# visitor on a light OS sees dark viz cells on a white page.
# /// script
# [tool.marimo.display]
# theme = "dark"
# ///
"""The Banister Constellation: interactive marimo notebook.

A constellation view of the fitness-fatigue model (FFM) literature lineage,
anchored by Banister 1975 + Calvert 1976. Reads pre-extracted nodes/edges
CSVs from public/data/ (built by extract.py against the local DuckDB).

Rendering uses vis-network (via CDN) inside an mo.iframe — pure JS in the
browser, no Python-side viz package. All other Python deps (pandas, numpy,
networkx) are Pyodide-shipped.
"""

import marimo

__generated_with = "0.23.0"
app = marimo.App(
    width="full",
    app_title="The Banister Constellation",
    css_file=None,
    # Loading overlay for the 30-60 s Pyodide cold start (removed once the first cell renders).
    html_head_file="deploy/loading_head.html",
)


@app.cell
def _():
    import json
    import math
    import marimo as mo
    import pandas as pd
    import numpy as np
    import networkx as nx
    return json, math, mo, np, nx, pd


@app.cell
def _(mo):
    mo.md(
        r"""
        # The Banister Constellation
        ### A citation network of the fitness-fatigue model lineage

        Every node is a paper. Every edge is a citation. The trunk runs from **Banister 1975** and
        **Calvert 1976**, the founding equations of the FFM family, out through five decades
        of variants, critiques, and Bayesian extensions. **White rings** mark the direct
        Banister lineage. Hover for details; drag to pan; scroll to zoom. Best on a desktop:
        on a touch screen, drag to pan and pinch to zoom.

        Built from a DuckDB literature index (networkx → vis-network).
        """
    )
    return


@app.cell
def _(mo, pd):
    try:
        base = mo.notebook_location()
        nodes_url = str(base / "public" / "data" / "nodes.csv")
        edges_url = str(base / "public" / "data" / "edges.csv")
        vendor_url = str(base / "public" / "vendor" / "vis-network-9.1.9.min.js")
    except Exception:
        nodes_url = "public/data/nodes.csv"
        edges_url = "public/data/edges.csv"
        vendor_url = "public/vendor/vis-network-9.1.9.min.js"

    nodes_df = pd.read_csv(nodes_url)
    edges_df = pd.read_csv(edges_url)

    # Vendored vis-network — inlined into the iframe HTML so the deployed
    # artifact has no CDN dependency at runtime.
    try:
        import urllib.request
        vis_network_js = urllib.request.urlopen(vendor_url).read().decode("utf-8")
    except Exception:
        with open("public/vendor/vis-network-9.1.9.min.js", encoding="utf-8") as _vf:
            vis_network_js = _vf.read()

    nodes_df["year"] = pd.to_numeric(nodes_df["year"], errors="coerce")
    nodes_df["citation_count"] = pd.to_numeric(
        nodes_df["citation_count"], errors="coerce"
    ).fillna(0).astype(int)

    def _to_bool(s):
        if isinstance(s, str):
            return s.strip().lower() in ("true", "1", "yes", "t")
        return bool(s)

    nodes_df["is_seed"] = nodes_df["is_seed"].map(_to_bool)
    nodes_df["is_banister_lineage"] = nodes_df["is_banister_lineage"].map(_to_bool)
    cols_str = ("label", "family", "paradigm", "title", "authors", "venue")
    for col in cols_str:
        nodes_df[col] = nodes_df[col].fillna("").astype(str)
    if "extension_family" in nodes_df.columns:
        nodes_df["extension_family"] = nodes_df["extension_family"].fillna("").astype(str)
    else:
        nodes_df["extension_family"] = ""

    # Effective family drives color, shape, legend and the Families filter alike:
    # the seed's own family, else the inferred extension_family. One-node
    # families share the "other" slot.
    def _eff(row):
        _f = row["family"] if row["is_seed"] else (row["extension_family"].strip() or "extended")
        return {"perpot": "other", "rt_specific": "other"}.get(_f, _f)

    nodes_df["eff_family"] = nodes_df.apply(_eff, axis=1)
    return edges_df, nodes_df, vis_network_js


@app.cell
def _(edges_df, nodes_df, np, nx, pd):
    G = nx.DiGraph()
    for _, row in nodes_df.iterrows():
        G.add_node(row["doi"], **row.to_dict())
    for _, row in edges_df.iterrows():
        if row["source"] in G and row["target"] in G:
            G.add_edge(row["source"], row["target"], kind=row["kind"])

    np.random.seed(7)
    pos_seed = {}
    for _n, _attrs in G.nodes(data=True):
        _year = _attrs.get("year")
        if pd.isna(_year):
            _year = 2000
        _fr = _attrs.get("family_rank", 9)
        _x0 = (float(_year) - 1975) / 6.0
        _y0 = -float(_fr) + np.random.uniform(-0.3, 0.3)
        pos_seed[_n] = np.array([_x0, _y0], dtype=float)

    pos = nx.spring_layout(
        G.to_undirected(),
        pos=pos_seed,
        k=0.9,
        iterations=120,
        seed=7,
        weight=None,
    )
    return G, pos


@app.cell
def _(mo, nodes_df):
    year_lo = int(nodes_df["year"].dropna().min())
    year_hi = int(nodes_df["year"].dropna().max())

    year_range = mo.ui.range_slider(
        start=year_lo, stop=year_hi, step=1, value=[year_lo, year_hi],
        label="Year range", full_width=True,
    )
    min_cites = mo.ui.slider(
        start=0, stop=500, step=10, value=0, label="Min. citations", show_value=True,
    )
    highlight_banister = mo.ui.switch(value=True, label="Highlight Banister lineage")
    only_banister = mo.ui.switch(value=False, label="Show only Banister lineage")

    _fam_names = {
        "classical": "Classical", "variable_dose": "Variable dose", "other": "Other models",
        "statistical_critique": "Statistical critique", "bayesian_hier": "Bayesian",
        "review": "Review", "extended": "Other extensions",
    }
    _present = [_k for _k in _fam_names if _k in set(nodes_df["eff_family"])]
    family_filter = mo.ui.multiselect(
        options={_fam_names[_k]: _k for _k in _present},
        value=[_fam_names[_k] for _k in _present],
        label="Families",
    )

    search = mo.ui.text(placeholder="search title / authors / label…", label="Find")

    controls = mo.vstack([
        mo.md("### Controls"),
        year_range,
        min_cites,
        family_filter,
        mo.hstack([highlight_banister, only_banister], justify="start", gap=2),
        search,
    ])
    controls
    return (
        controls,
        family_filter,
        highlight_banister,
        min_cites,
        only_banister,
        search,
        year_range,
    )


@app.cell
def _(
    G,
    family_filter,
    highlight_banister,
    json,
    math,
    min_cites,
    mo,
    np,
    only_banister,
    search,
    vis_network_js,
    year_range,
):
    _yr_lo, _yr_hi = year_range.value
    _fam_keep = set(family_filter.value)
    _needle = (search.value or "").strip().lower()

    ANCHOR_DOIS = {"manual:banister1975", "10.1109/tsmc.1976.5409179"}
    # Okabe-Ito + a vis-network shape per family; keep in sync with build_html.py.
    FAMILY_COLORS = {
        "classical":            "#E69F00",
        "variable_dose":        "#56B4E9",
        "other":                "#CC79A7",
        "statistical_critique": "#D55E00",
        "bayesian_hier":        "#F0E442",
        "review":               "#009E73",
    }
    FAMILY_SHAPES = {
        "classical": "dot", "variable_dose": "square", "other": "triangleDown",
        "statistical_critique": "triangle", "bayesian_hier": "diamond", "review": "hexagon",
    }
    LINEAGE = "#FFFFFF"

    def _esc(s):
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&#39;"))

    def _hex_to_rgba(hex_str, alpha):
        h = hex_str.lstrip("#")
        return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"

    def _hover(a, cites, is_lin, effective_fam):
        label = (a.get("label") or "").strip()
        title = (a.get("title") or "").strip()
        authors = (a.get("authors") or "")[:160].strip()
        venue = (a.get("venue") or "").strip()
        yr = a.get("year")
        yr_str = ""
        if yr is not None and not (isinstance(yr, float) and np.isnan(yr)):
            yr_str = str(int(yr))
        fam = effective_fam or (a.get("family") or "")

        heading = title if title else label
        sub = label if (title and label and title != label) else ""

        bits = []
        if heading:
            bits.append(f"<div style='font-size:13px;font-weight:600;line-height:1.35;margin-bottom:4px'>{_esc(heading[:180])}</div>")
        if sub:
            bits.append(f"<div style='color:#aab2c4;font-size:11px;margin-bottom:4px'>{_esc(sub)}</div>")
        if authors:
            bits.append(f"<div style='font-size:11px;margin-bottom:2px'>{_esc(authors)}</div>")
        vy = " · ".join(x for x in [venue, yr_str] if x)
        if vy:
            bits.append(f"<div style='font-size:11px;color:#9aa3b8;margin-bottom:4px'>{_esc(vy)}</div>")
        bits.append(
            f"<div style='font-size:11px;color:#9aa3b8'>"
            f"<span style='color:#E8E8EA'>{cites:,}</span> citations"
            f" · family: <span style='color:#E8E8EA'>{_esc(fam)}</span></div>"
        )
        if is_lin:
            bits.append("<div style='color:#FFFFFF;font-size:11px;margin-top:4px'><b>★ Banister lineage</b></div>")
        return "".join(bits)

    vis_nodes, vis_edges, lineage_ids = [], [], []
    visible = set()
    for _node, _a in G.nodes(data=True):
        _y = _a.get("year")
        if _y is None or (isinstance(_y, float) and np.isnan(_y)):
            continue
        if not (_yr_lo <= _y <= _yr_hi):
            continue
        if _a.get("eff_family") not in _fam_keep:
            continue
        _cites = max(int(_a.get("citation_count", 0) or 0), 0)
        if _cites < min_cites.value:
            continue
        _is_lin = bool(_a.get("is_banister_lineage"))
        if only_banister.value and not _is_lin:
            continue
        if _needle:
            _hay = " ".join(str(_a.get(k) or "") for k in ("label", "title", "authors", "doi")).lower()
            if _needle not in _hay:
                continue
        _is_anchor = _node in ANCHOR_DOIS
        _is_seed = bool(_a.get("is_seed"))
        _label = _a.get("label") or ""
        _effective_fam = _a.get("eff_family") or "extended"
        _base_hex = FAMILY_COLORS.get(_effective_fam, "#999999")

        _size = 10 + 22 * (math.log10(_cites + 1) / math.log10(2001))
        if _is_anchor: _size += 12
        elif _is_seed: _size += 4

        if _is_seed:
            _fill = _base_hex
            # Lineage = white ring; other seeds ring in their own color so white stays unique.
            _border = LINEAGE if (_is_lin and highlight_banister.value) else _base_hex
            _border_w = 4 if _is_anchor else (3 if (_is_lin and highlight_banister.value) else 1.6)
        else:
            _fill = _hex_to_rgba(_base_hex, 0.45)
            _border = _hex_to_rgba(_base_hex, 0.7)
            _border_w = 0.8
        _shape = "star" if _is_anchor else FAMILY_SHAPES.get(_effective_fam, "dot")

        vis_nodes.append({
            "id": _node,
            "label": _label if (_is_seed or _is_anchor) else "",
            "title": _hover(_a, _cites, _is_lin, _effective_fam),
            "year": int(_y),
            "shape": _shape,
            "size": round(_size, 1),
            "color": {
                "background": _fill,
                "border": _border,
                "highlight": {"background": _base_hex, "border": LINEAGE},
                "hover": {"background": _base_hex, "border": LINEAGE},
            },
            "borderWidth": _border_w,
            "borderWidthSelected": _border_w + 1,
            "font": {"color": "#E8E8EA", "size": 12, "face": "Inter, system-ui, sans-serif",
                     "strokeWidth": 0, "background": "rgba(14,17,23,0.7)"},
        })
        visible.add(_node)
        if _is_lin:
            lineage_ids.append(_node)

    for _u, _v, _eattrs in G.edges(data=True):
        if _u not in visible or _v not in visible:
            continue
        if _eattrs.get("kind") == "manual":
            vis_edges.append({
                "from": _u, "to": _v,
                "color": {"color": "rgba(255,255,255,0.7)", "highlight": LINEAGE},
                "width": 1.6, "smooth": {"type": "continuous"},
            })
        else:
            vis_edges.append({
                "from": _u, "to": _v,
                "color": {"color": "rgba(180,180,200,0.18)", "highlight": "rgba(255,255,255,0.6)"},
                "width": 0.6, "smooth": {"type": "continuous"},
            })

    def _safe_json(obj):
        # Harden against </script> injection if any string field contains the literal.
        return json.dumps(obj).replace("</", "<\\/")

    _nodes_json = _safe_json(vis_nodes)
    _edges_json = _safe_json(vis_edges)
    _lineage_json = _safe_json(lineage_ids)

    _html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:#0E1117;color:#E8E8EA;font-family:Inter,system-ui,sans-serif;height:100%;overflow:hidden;}
#net{width:100vw;height:100vh;position:relative;z-index:2;}
#legend{position:fixed;top:12px;left:12px;z-index:10;background:rgba(20,24,33,0.85);
        border:1px solid #2a2f3d;border-radius:8px;padding:10px 12px;font-size:12px;
        line-height:1.55;max-width:240px;}
#legend h4{margin:0 0 6px 0;font-size:13px;font-weight:600;}
#legend svg{width:12px;height:12px;margin-right:6px;vertical-align:-1px;}
.controls{position:fixed;top:12px;right:12px;z-index:10;background:rgba(20,24,33,0.85);
          border:1px solid #2a2f3d;border-radius:8px;padding:8px 10px;font-size:12px;}
.controls button{background:#1a1f2e;color:#E8E8EA;border:1px solid #3a4156;
                 border-radius:4px;padding:4px 10px;cursor:pointer;font-family:inherit;
                 font-size:12px;margin-right:4px;}
.controls button:hover{border-color:#FFFFFF;}
@media (max-width:600px){
  .controls{left:12px;right:12px;display:flex;gap:4px;padding:6px;}
  .controls button{flex:1;margin:0;padding:6px 4px;min-height:32px;}
  #legend{top:62px;right:12px;max-width:none;padding:8px 10px;font-size:11px;line-height:1.45;
          column-count:2;column-gap:12px;}
  #legend h4{column-span:all;}
}
.vis-tooltip{background:#1a1f2e!important;color:#E8E8EA!important;border:1px solid #5a6377!important;
             padding:8px 10px!important;font-family:inherit!important;font-size:12px!important;
             max-width:380px!important;border-radius:6px!important;}
#year-axis{position:fixed;inset:0;pointer-events:none;z-index:1;}
#year-axis .gridline{position:absolute;left:0;right:0;height:1px;background:rgba(80,90,110,0.18);}
#year-axis .label{position:absolute;left:8px;transform:translateY(-50%);
                  color:#aab2c4;font-size:11px;font-family:inherit;
                  background:rgba(14,17,23,0.7);padding:1px 6px;border-radius:3px;}
</style></head><body>
<div id="legend">
<h4>The Banister Constellation</h4>
<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#E69F00"><circle cx="6" cy="6" r="5"/></svg>Classical</div>
<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#56B4E9"><rect x="1" y="1" width="10" height="10"/></svg>Variable dose</div>
<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#CC79A7"><polygon points="1,1 11,1 6,11"/></svg>Other models</div>
<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#D55E00"><polygon points="6,1 11,11 1,11"/></svg>Statistical critique</div>
<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#F0E442"><polygon points="6,0.5 11.5,6 6,11.5 0.5,6"/></svg>Bayesian</div>
<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#009E73"><polygon points="3,1 9,1 12,6 9,11 3,11 0,6"/></svg>Review</div>
<div><svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="none" stroke="#FFFFFF" stroke-width="2"/></svg>Banister lineage</div>
<div><svg viewBox="0 0 12 12" aria-hidden="true" fill="#FFFFFF"><polygon points="6,0.5 7.5,4.5 11.5,4.6 8.3,7.1 9.4,11.2 6,8.8 2.6,11.2 3.7,7.1 0.5,4.6 4.5,4.5"/></svg>Founding equations</div>
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
const ALL_NODES_RAW = __NODES__;
const ALL_EDGES = __EDGES__;
const LINEAGE_IDS = new Set(__LINEAGE__);

const YEAR_MIN = 1974, YEAR_MAX = 2026;
const SPAN_PX = 2400;
function yearToY(y){if(y==null)y=(YEAR_MIN+YEAR_MAX)/2;return ((y-YEAR_MIN)/(YEAR_MAX-YEAR_MIN))*SPAN_PX - SPAN_PX/2;}

const ALL_NODES = ALL_NODES_RAW.map(n => {
  const node = Object.assign({}, n);
  if (typeof node.title === "string") {
    const el = document.createElement("div");
    el.innerHTML = node.title;
    node.title = el;
  }
  node.y = yearToY(node.year);
  node.x = (Math.random() - 0.5) * 900;
  node.fixed = { x: false, y: true };
  return node;
});

const nodesDS = new vis.DataSet(ALL_NODES);
const edgesDS = new vis.DataSet(ALL_EDGES);
const options = {
  nodes:{shape:"dot",scaling:{min:10,max:40}},
  edges:{arrows:{to:{enabled:false}},smooth:{type:"continuous",roundness:0.2},hoverWidth:0.5},
  physics:{enabled:true,solver:"forceAtlas2Based",
    forceAtlas2Based:{gravitationalConstant:-120,centralGravity:0.005,
      springLength:60,springConstant:0.05,damping:0.6,avoidOverlap:0.7},
    stabilization:{enabled:true,iterations:400,fit:true},minVelocity:0.5},
  interaction:{hover:true,tooltipDelay:80,dragNodes:true,dragView:true,zoomView:true},
  layout:{improvedLayout:false}};
const network = new vis.Network(document.getElementById("net"),{nodes:nodesDS,edges:edgesDS},options);
network.once("stabilizationIterationsDone",()=>{
  network.setOptions({physics:{enabled:false}});
  network.fit({animation:{duration:400}});
});

function drawYearAxis(){
  const axis = document.getElementById("year-axis");
  axis.querySelectorAll(".gridline,.label").forEach(t => t.remove());
  [1975,1985,1995,2005,2015,2025].forEach(yr => {
    const pt = network.canvasToDOM({x:0, y:yearToY(yr)});
    const line = document.createElement("div");
    line.className = "gridline"; line.style.top = pt.y + "px";
    axis.appendChild(line);
    const lbl = document.createElement("div");
    lbl.className = "label"; lbl.textContent = yr; lbl.style.top = pt.y + "px";
    axis.appendChild(lbl);
  });
}
network.on("afterDrawing", drawYearAxis);
window.addEventListener("resize", drawYearAxis);

function withReheat(fn){
  fn();
  network.setOptions({physics:{enabled:true}});
  network.once("stabilizationIterationsDone", () => {
    network.setOptions({physics:{enabled:false}});
    network.fit({animation:{duration:400}});
  });
}
function lineageOnly(){withReheat(() => {
  nodesDS.clear(); edgesDS.clear();
  nodesDS.add(ALL_NODES.filter(n => LINEAGE_IDS.has(n.id)));
  edgesDS.add(ALL_EDGES.filter(e => LINEAGE_IDS.has(e.from) && LINEAGE_IDS.has(e.to)));
});}
function lineageAll(){withReheat(() => {
  nodesDS.clear(); edgesDS.clear();
  nodesDS.add(ALL_NODES); edgesDS.add(ALL_EDGES);
});}
function fit(){network.fit({animation:{duration:400}});}
</script></body></html>"""
    _html = (
        _html
        .replace("__VIS_NETWORK_JS__", vis_network_js)
        .replace("__NODES__", _nodes_json)
        .replace("__EDGES__", _edges_json)
        .replace("__LINEAGE__", _lineage_json)
    )

    viz = mo.iframe(_html, height="780px", width="100%")
    viz
    return (viz,)


@app.cell
def _(G, mo, nodes_df, only_banister, year_range):
    _yr_lo, _yr_hi = year_range.value
    _vis = nodes_df[
        nodes_df["year"].between(_yr_lo, _yr_hi)
        & ((not only_banister.value) | nodes_df["is_banister_lineage"])
    ]

    _n_total = len(_vis)
    _n_seeds = int(_vis["is_seed"].sum())
    _n_lineage = int(_vis["is_banister_lineage"].sum())
    _n_edges_total = G.number_of_edges()

    mo.md(
        f"""
        <div style="display:flex; gap:2rem; padding:1rem 0; color:#888; font-size:0.92rem">
            <span><b style="color:#E8E8EA">{_n_total}</b> papers visible</span>
            <span><b style="color:#E8E8EA">{_n_seeds}</b> curated seeds</span>
            <span><b style="color:#FFFFFF">{_n_lineage}</b> in Banister lineage</span>
            <span><b style="color:#E8E8EA">{_n_edges_total}</b> citation edges in full graph</span>
        </div>
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ---
        ### Legend
        - **Stars:** Banister 1975 and Calvert 1976, the founding equations.
        - **Larger nodes:** curated seed papers from the canonical FFM lineage.
        - **White ring:** directly descended from Banister via the manually curated parent_doi tree.
        - **White edges:** manually asserted lineage links (parent_doi).
        - **Faint edges:** automatically discovered citations from Semantic Scholar and CrossRef.
        - **Node size:** log10(citation count).
        - **Node color and shape:** methodological family. Classical (circle), variable dose (square),
          other models (down triangle), statistical critique (triangle), Bayesian (diamond), review (hexagon).
          The palette is Okabe-Ito, and the shapes keep families distinguishable without color.

        Data extracted from a DuckDB literature index (Semantic Scholar forward citations, CrossRef
        references, and manually curated FFM seeds). See `extract.py`.
        """
    )
    return


if __name__ == "__main__":
    app.run()
