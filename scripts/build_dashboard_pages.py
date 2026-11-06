"""Add (or rebuild) the "Players" and "Betting" pages of the NFL Efficiency dashboard.

    python scripts/build_dashboard_pages.py      # edits src/dashboards/nfl_efficiency.lvdash.json in place
    databricks bundle deploy -t prod

Datasets come from src/dashboards/players_betting_datasets.sql. Headshots and team logos are URL columns
rendered by table image cells (table widget v1: displayAs "image" + imageUrlTemplate). Re-running replaces
these pages and datasets; the original "NFL Efficiency" page is not touched.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "src/dashboards/nfl_efficiency.lvdash.json"
SQL = ROOT / "src/dashboards/players_betting_datasets.sql"
PAGES = {"players": "Players", "betting": "Betting"}


def datasets() -> list[dict]:
    out = []
    for block in SQL.read_text().split("-- @")[1:]:
        name, body = block.split("\n", 1)
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("--")).strip().rstrip(";")
        out.append({"name": name.strip(), "displayName": name.strip(), "queryLines": [l + "\n" for l in body.splitlines()]})
    return out


def col(field, title, kind="string", fmt=None, image=False, width=None):
    c = {"fieldName": field, "booleanValues": ["false", "true"], "imageUrlTemplate": "{{ @ }}", "imageTitleTemplate": "{{ @ }}",
         "imageWidth": "", "imageHeight": "", "linkUrlTemplate": "{{ @ }}", "linkTextTemplate": "{{ @ }}",
         "linkTitleTemplate": "{{ @ }}", "linkOpenInNewTab": True, "type": kind,
         "displayAs": "image" if image else ("number" if kind in ("integer", "float") else "string"),
         "visible": True, "title": title, "allowSearch": False,
         "alignContent": "center" if image else ("right" if kind in ("integer", "float") else "left"),
         "allowHTML": False, "highlightLinks": False, "useMonospaceFont": False, "preserveWhitespace": False}
    if image:
        c.update(imageWidth=str(width or 40), imageHeight=str(width or 40), imageTitleTemplate="")
    if fmt:
        c["numberFormat"] = fmt
    return c


def table(name, ds, title, columns, desc=None):
    for i, c in enumerate(columns):
        c["order"] = 100000 + i
    frame = {"showTitle": True, "title": title}
    if desc:
        frame.update(showDescription=True, description=desc)
    return {"name": name,
            "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": True,
                                                          "fields": [{"name": c["fieldName"], "expression": f"`{c['fieldName']}`"} for c in columns]}}],
            "spec": {"version": 1, "widgetType": "table", "allowHTMLByDefault": False, "condensed": False, "itemsPerPage": 32,
                     "withRowNumber": False, "invisibleColumns": [], "encodings": {"columns": columns}, "frame": frame}}


def bar(name, ds, title, x, y, ytitle, desc=None):
    agg = f"avg({y})"
    frame = {"showTitle": True, "title": title}
    if desc:
        frame.update(showDescription=True, description=desc)
    return {"name": name,
            "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": False,
                                                          "fields": [{"name": x, "expression": f"`{x}`"},
                                                                     {"name": agg, "expression": f"AVG(`{y}`)"}]}}],
            "spec": {"version": 3, "widgetType": "bar", "encodings": {
                "x": {"fieldName": x, "scale": {"type": "categorical", "sort": {"by": "y-reversed"}}, "displayName": "Team"},
                "y": {"fieldName": agg, "scale": {"type": "quantitative"}, "displayName": ytitle, "axis": {"title": ytitle}},
                "label": {"show": True}}, "frame": frame}}


def season_filter(name, ds_names):
    queries, fields = [], []
    for ds in ds_names:
        qn = f"filter_season_{ds}"
        queries.append({"name": qn, "query": {"datasetName": ds, "disaggregated": False, "fields": [
            {"name": "season", "expression": "`season`"},
            {"name": "season_associativity", "expression": "COUNT_IF(`associative_filter_predicate_group`)"}]}})
        fields.append({"fieldName": "season", "displayName": "season", "queryName": qn})
    return {"name": name, "queries": queries, "spec": {
        "version": 2, "widgetType": "filter-single-select", "encodings": {"fields": fields},
        "frame": {"showTitle": True, "title": "Season"},
        "selection": {"defaultSelection": {"values": {"dataType": "INTEGER", "values": [{"value": "2026"}]}}}}}


def text(name, md):
    return {"name": name, "multilineTextboxSpec": {"lines": [l + "\n" for l in md.split("\n")]}}


HEAD = ("headshot_url", "")
players_layout = [
    (text("players_head", "# Player Leaders\nRegular season. Headshots and logos load from nfl.com and ESPN."), (0, 0, 6, 1)),
    (season_filter("players_season", ["passing_leaders", "rushing_leaders", "receiving_leaders"]), (0, 1, 2, 1)),
    (table("passing_table", "passing_leaders", "Passing", [
        col("rk", "#", "integer", "0"), col("headshot_url", "", image=True, width=44), col("player_name", "Player"),
        col("team_logo_url", "", image=True, width=28), col("games", "G", "integer", "0"),
        col("completions", "Cmp", "integer", "0"), col("pass_attempts", "Att", "integer", "0"),
        col("passing_yards", "Yds", "integer", "0"), col("passing_tds", "TD", "integer", "0"),
        col("interceptions", "Int", "integer", "0"), col("epa_per_dropback", "EPA/dropback", "float", "0.000")],
        "Top 15 by passing yards. EPA/dropback shown for QBs with 100+ dropbacks."), (0, 2, 6, 8)),
    (table("rushing_table", "rushing_leaders", "Rushing", [
        col("rk", "#", "integer", "0"), col("headshot_url", "", image=True, width=40), col("player_name", "Player"),
        col("team_logo_url", "", image=True, width=26), col("carries", "Car", "integer", "0"),
        col("rushing_yards", "Yds", "integer", "0"), col("yards_per_carry", "Y/C", "float", "0.0"),
        col("rushing_tds", "TD", "integer", "0")], "Top 15 by rushing yards."), (0, 10, 3, 9)),
    (table("receiving_table", "receiving_leaders", "Receiving", [
        col("rk", "#", "integer", "0"), col("headshot_url", "", image=True, width=40), col("player_name", "Player"),
        col("team_logo_url", "", image=True, width=26), col("targets", "Tgt", "integer", "0"),
        col("receptions", "Rec", "integer", "0"), col("receiving_yards", "Yds", "integer", "0"),
        col("receiving_tds", "TD", "integer", "0")], "Top 15 by receiving yards."), (3, 10, 3, 9)),
]
betting_layout = [
    (text("betting_head", "# Betting\nRegular-season records against the closing spread and the closing over/under. "
                          "ATS = against the spread; pushes are excluded from percentages."), (0, 0, 6, 1)),
    (season_filter("betting_season", ["team_betting"]), (0, 1, 2, 1)),
    (table("betting_table", "team_betting", "Records against the spread and the total", [
        col("team_logo_url", "", image=True, width=30), col("team_name", "Team"), col("record", "Record"),
        col("ats_record", "ATS"), col("ats_cover_pct", "Cover %", "float", "0.0"),
        col("ats_as_favorite", "ATS as fav"), col("ats_as_underdog", "ATS as dog"),
        col("outright_underdog_wins", "Upsets", "integer", "0"), col("over_under", "O/U"),
        col("over_pct", "Over %", "float", "0.0"), col("avg_cover_margin", "Avg cover", "float", "0.0"),
        col("avg_total_vs_line", "Avg vs total", "float", "0.0")],
        "Sorted by cover rate. Avg cover = average margin vs. the spread; avg vs total = average points above the closing total."),
     (0, 2, 6, 11)),
    (bar("ats_bar", "team_betting", "ATS cover %", "team", "ats_cover_pct", "Cover %"), (0, 13, 3, 7)),
    (bar("over_bar", "team_betting", "Over %", "team", "over_pct", "Over %"), (3, 13, 3, 7)),
]


def page(key, layout):
    cells = set()
    for w, (x, y, wd, h) in layout:
        for cx in range(x, x + wd):
            for cy in range(y, y + h):
                assert (cx, cy) not in cells, (key, w["name"])
                cells.add((cx, cy))
    return {"name": key, "displayName": PAGES[key], "pageType": "PAGE_TYPE_CANVAS",
            "layout": [{"widget": w, "position": {"x": x, "y": y, "width": wd, "height": h}} for w, (x, y, wd, h) in layout]}


def main() -> None:
    dash = json.loads(DASH.read_text())
    new_ds = datasets()
    names = {d["name"] for d in new_ds}
    dash["datasets"] = [d for d in dash["datasets"] if d["name"] not in names] + new_ds
    dash["pages"] = [p for p in dash["pages"] if p["name"] not in PAGES] + [page("players", players_layout), page("betting", betting_layout)]
    # every widget field must exist in its dataset's SELECT list
    cols = {d["name"]: set(re.findall(r"\bAS\s+(\w+)|\b[a-z]\.(\w+)", "".join(d["queryLines"]))) for d in dash["datasets"]}
    flat = {k: {x for tup in v for x in tup if x} for k, v in cols.items()}
    for p in dash["pages"]:
        if p["name"] not in PAGES:
            continue
        for e in p["layout"]:
            for q in e["widget"].get("queries", []):
                for f in q["query"]["fields"]:
                    for c in re.findall(r"`(\w+)`", f["expression"]):
                        assert c in flat[q["query"]["datasetName"]] or c == "associative_filter_predicate_group", (q["query"]["datasetName"], c)
    DASH.write_text(json.dumps(dash, indent=2) + "\n")
    print(f"pages: {[p['displayName'] for p in dash['pages']]} | datasets: {[d['name'] for d in dash['datasets']]}")


if __name__ == "__main__":
    main()
