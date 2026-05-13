# Social-card brief — 1200×630 OG image

## What ships today

The PNGs already on disk are the OG cards. No further work required for v0.1.

| File | Use |
|---|---|
| `dist_static/citation_network_card.png` | **Default OG/Twitter card.** 1200×630, no labels — minimal, atmospheric. The visual interest comes from the constellation pattern alone. |
| `dist_static/citation_network_card_labeled.png` | **Alternative** for posts/contexts where the labels add narrative (LinkedIn longform, blog header). Same dimensions, seed labels rendered. |
| `dist_static/citation_network.png` | Hero image for the case-study page (1600×1200). Not for OG — too tall. |

Pulled into the portfolio site at build time as `citation-network/assets/og.png`
(see the `netlify.toml` `build.command` curl steps in `NEXT_SESSION_NETLIFY.md`).

## Regeneration

`python render_static.py` rebuilds all three. The matplotlib renderer is
deterministic at `seed=7` (default), so re-runs produce visually identical
output as long as `public/data/nodes.csv` + `edges.csv` are unchanged.

## Design notes (for future iterations)

- Dark background `#0E1117` (matches the interactive viz).
- Gold edges (`#FFC850` α≈0.7) for manual lineage links — these are the
  visual signature of the figure; they're what catch the eye in a feed.
- Star markers for the two founding anchors (Banister 1975, Calvert 1976).
- Halos behind lineage nodes draw attention to the curated chain.
- No title overlay on the OG card itself — title comes from the og:title
  meta tag, so the image can stay graphic-only. The PNG is the hook; the
  text lives in the social preview.

## Validation checklist

Before announcing publicly, run these previews:
- LinkedIn post composer — paste `https://jacobbowie.com/citation-network/`,
  confirm the card image renders at expected dimensions.
- Twitter Card Validator (`cards-dev.twitter.com/validator`) — same.
- Facebook Sharing Debugger — same.
- Discord embed preview — paste the URL in a DM-to-self.
