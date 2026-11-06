"""Build the Vega-Lite spec for the "Offense vs. Defense" logo scatter (AI/BI custom visualization).

AI/BI custom visualizations only render image marks from *inline* base64 `data:` URLs (≤37 KB each).
Remote URLs and field-driven URLs (`url: {field: ...}`) are not allowed. So instead of one image
layer driven by a logo column, this writes one image layer per logo with the logo embedded as a
literal, filtered to the team codes that use it (e.g. LV + OAK). Teams with no logo fall back to a
text label.

    pip install pillow
    python scripts/build_logo_scatter.py            # writes src/dashboards/offense_defense_logos.vl.json

In the dashboard: add a widget on the `team_season` dataset → Advanced → Custom Viz, add the Fields
team, record, net_epa, offense_epa, defense_epa (names exactly as written), paste the spec.
"""
import base64
import io
import json
import urllib.request
from collections import defaultdict
from pathlib import Path

from PIL import Image

TEAMS_URL = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
OUT = Path(__file__).resolve().parent.parent / "src/dashboards/offense_defense_logos.vl.json"
LOGO_PX = 64            # stored size; rendered at LOGO_DRAW px
LOGO_DRAW = 30
MAX_DATA_URI = 37 * 1024  # AI/BI limit per image


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def logo_data_uri(url: str) -> str:
    img = Image.open(io.BytesIO(fetch(url))).convert("RGBA")
    img.thumbnail((LOGO_PX, LOGO_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    assert len(uri) <= MAX_DATA_URI, (url, len(uri))
    return uri


def main() -> None:
    import csv

    rows = list(csv.DictReader(io.StringIO(fetch(TEAMS_URL).decode())))
    codes_by_logo = defaultdict(list)            # one layer per distinct logo (LA/LAR/STL share one)
    for r in rows:
        codes_by_logo[r["team_logo_espn"]].append(r["team_abbr"])

    xy = {
        "x": {"field": "offense_epa", "type": "quantitative", "title": "Offense EPA/play  →  better",
              "scale": {"zero": False, "padding": 24}},
        "y": {"field": "defense_epa", "type": "quantitative", "title": "Defense EPA/play (sign flipped)  →  better",
              "scale": {"zero": False, "padding": 24}},
    }
    tooltip = [
        {"field": "team", "title": "Team"},
        {"field": "record", "title": "Record"},
        {"field": "net_epa", "title": "Net EPA/play", "format": "+.3f"},
        {"field": "offense_epa", "title": "Offense EPA/play", "format": "+.3f"},
        {"field": "defense_epa", "title": "Defense EPA/play", "format": "+.3f"},
    ]

    layers = [
        # league-average guides split the chart into four quadrants
        {"mark": {"type": "rule", "strokeDash": [4, 4], "opacity": 0.4},
         "encoding": {"x": {"aggregate": "mean", "field": "offense_epa", "type": "quantitative"}}},
        {"mark": {"type": "rule", "strokeDash": [4, 4], "opacity": 0.4},
         "encoding": {"y": {"aggregate": "mean", "field": "defense_epa", "type": "quantitative"}}},
    ]
    # light disc behind every logo, so dark logos (NYG, DAL, NE...) stay readable in dark mode
    layers.append({"mark": {"type": "point", "filled": True, "color": "#f5f6f7", "opacity": 0.92,
                            "size": LOGO_DRAW * LOGO_DRAW * 1.35, "stroke": "#9aa4ae", "strokeWidth": 0.5},
                   "encoding": xy})
    all_codes = []
    for url, codes in sorted(codes_by_logo.items(), key=lambda kv: kv[1][0]):
        all_codes += codes
        layers.append({
            "transform": [{"filter": {"field": "team", "oneOf": sorted(codes)}}],
            "mark": {"type": "image", "url": logo_data_uri(url), "width": LOGO_DRAW, "height": LOGO_DRAW},
            "encoding": xy,
        })
    # fallback: any team code without a logo is drawn as its abbreviation
    layers.append({
        "transform": [{"filter": {"not": {"field": "team", "oneOf": sorted(all_codes)}}}],
        "mark": {"type": "text", "fontWeight": "bold"},
        "encoding": {**xy, "text": {"field": "team"}},
    })
    # invisible hover targets on top, so every logo shows the tooltip
    layers.append({"mark": {"type": "point", "size": 700, "opacity": 0, "filled": True},
                   "encoding": {**xy, "tooltip": tooltip}})

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "NFL offense vs. defense EPA per play, one logo per team. Top-right = good at both.",
        "data": {"name": "databricks_query"},
        "width": "container",
        "height": "container",
        "layer": layers,
    }
    OUT.write_text(json.dumps(spec, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB, {len(codes_by_logo)} logos, {len(all_codes)} team codes)")


if __name__ == "__main__":
    main()
