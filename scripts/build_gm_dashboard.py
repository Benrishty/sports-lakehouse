"""Build the "GM Office" dashboard: src/dashboards/gm_office.lvdash.json.

    python scripts/build_gm_dashboard.py && databricks bundle deploy -t prod

One Team picker (a global filter, default NYG) drives every page: it binds to every dataset with a `team`
column. League-wide datasets name the column `club` so the picker leaves them whole. Datasets come from
src/dashboards/gm_office_datasets.sql. Layouts use AI/BI's 12-column grid. Widget helpers are shared with
build_dashboard_pages.py.
"""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src/dashboards/gm_office.lvdash.json"
SQL = ROOT / "src/dashboards/gm_office_datasets.sql"
DEFAULT_TEAM = "NYG"

_spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts/build_dashboard_pages.py")
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)
col, table, bar, text = pages.col, pages.table, pages.bar, pages.text


def datasets() -> list[dict]:
    out = []
    for block in SQL.read_text().split("-- @")[1:]:
        name, body = block.split("\n", 1)
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("--")).strip().rstrip(";")
        out.append({"name": name.strip(), "displayName": name.strip(), "queryLines": [l + "\n" for l in body.splitlines()]})
    return out


def team_filter(ds_with_team: list[str]) -> dict:
    queries = [{"name": f"team_{ds}", "query": {"datasetName": ds, "disaggregated": False,
                                                 "fields": [{"name": "team", "expression": "`team`"}]}} for ds in ds_with_team]
    return {"name": "team_picker", "queries": queries, "spec": {
        "version": 2, "widgetType": "filter-single-select",
        "encodings": {"fields": [{"fieldName": "team", "displayName": "Team", "queryName": q["name"]} for q in queries]},
        "selection": {"defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": DEFAULT_TEAM}]}}},
        "frame": {"showTitle": True, "title": "Your team"}}}


IMG = dict(image=True)
LAYOUT = {
    "report_card": ("Team Report Card", [
        (text("rc_head", "# GM Office\nPick your team in the filter bar. Current regular season. Ranks are out of 32 "
                         "(1 = best, direction-aware). Tiers: 🟢 1-8, 🟡 9-16, 🟠 17-24, 🔴 25-32."), (0, 0, 12, 2)),
        (table("rc_summary", "gm_summary", "Where we stand", [
            col("team_logo_url", "", **IMG, width=40), col("team_name", "Team"), col("record", "Record"),
            col("division", "Division"), col("division_rank", "Div rank", "integer", "0"),
            col("division_games_back", "GB", "float", "0.0"), col("conference_seed", "Seed (approx.)", "integer", "0"),
            col("net_epa_rank", "Net EPA rank", "integer", "0"), col("luck_gap", "Luck gap", "integer", "0"),
            col("ats_record", "ATS")],
            "Seed approximates NFL tiebreakers with point differential. Luck gap < 0 = playing better than the record."),
         (0, 2, 12, 3)),
        (table("rc_table", "gm_report_card", "Report card", [
            col("phase", "Phase"), col("metric", "Metric"), col("value", "Us"), col("league_avg", "League avg"),
            col("league_rank", "Rank", "integer", "0"), col("tier", "Tier")],
            "Every phase of the game vs. the league."), (0, 5, 7, 15)),
        (bar("rc_pct", "gm_percentiles", "Percentile by metric (100 = best in league)", "metric", "percentile", "Percentile"),
         (7, 5, 5, 15)),
        (table("rc_fresh", "gm_freshness", "Data as of", [
            col("source", "Source"), col("latest_season", "Season", "integer", "0"), col("latest_week", "Week / games", "integer", "0"),
            col("cadence", "Cadence")], "PFR advanced stats are season files that lag during the season."), (0, 20, 12, 5)),
    ]),
    "roster_cap": ("Roster & Cap", [
        (text("cap_head", "## Roster & Cap\nTwo separate questions per player: **how good is he** (production rate vs. his position group) and "
                          "**is the contract good value** (production percentile minus pay percentile). Rates, not totals, so "
                          "missed games do not count against anyone. Pay is APY ($M) from OverTheCap, not the exact cap hit. "
                          "OL and specialists are not scored (no individual blocking data)."), (0, 0, 12, 2)),
        (bar("cap_bar", "gm_cap_allocation", "Spend vs. league average by position group (percentage points of team APY)",
             "position_group", "vs_league_pts", "Pts vs. league"), (0, 2, 6, 9)),
        (table("cap_table", "gm_cap_allocation", "Cap allocation", [
            col("position_group", "Group"), col("players", "Players", "integer", "0"), col("apy_m", "APY $M", "float", "0.0"),
            col("team_share_pct", "Our share %", "float", "0.0"), col("league_avg_pct", "League %", "float", "0.0"),
            col("top8_avg_pct", "Top-8 teams %", "float", "0.0"), col("vs_league_pts", "Vs league", "float", "0.0")],
            "Top-8 = the 8 best teams by current net EPA."), (6, 2, 6, 9)),
        (table("value_table", "gm_roster_value", "Contracts vs. production", [
            col("headshot_url", "", **IMG, width=36), col("player_name", "Player"), col("position_group", "Pos"),
            col("age", "Age", "integer", "0"), col("apy_m", "APY $M", "float", "0.0"), col("final_season", "Thru", "integer", "0"),
            col("games", "Games"), col("availability", "Availability"),
            col("performance", "How good"), col("contract", "Contract"), col("value_score", "Value", "integer", "0"),
            col("production_metric_name", "Measured by"), col("production", "Rate", "float", "0.00"), col("judged_on", "Judged on")],
            "How good = production percentile in the position group (elite 90+, very good 70-90, average 40-70). Contract = production "
            "percentile minus pay percentile (bargain >= +25, overpaid <= -25). Players with under 4 games this season are judged on last season."),
         (0, 11, 12, 13)),
        (table("expiring_table", "gm_expiring", "Contracts ending this season: re-sign, replace or let walk", [
            col("headshot_url", "", **IMG, width=32), col("player_name", "Player"), col("position_group", "Pos"),
            col("age", "Age", "integer", "0"), col("apy_m", "APY $M", "float", "0.0"), col("role", "Role"),
            col("snap_pct", "Snap %", "integer", "0"), col("value_score", "Value", "integer", "0")]), (0, 24, 12, 9)),
    ]),
    "personnel": ("Personnel", [
        (text("pers_head", "## Personnel\nCurrent-season contributors (25%+ snap share) with the advanced metric that fits each "
                           "role: offensive EPA, Next Gen Stats (RYOE per carry, receiver separation, YAC over expected) and "
                           "play-by-play defensive credit per 100 snaps."), (0, 0, 12, 2)),
        (table("pers_table", "gm_personnel", "Player performance", [
            col("headshot_url", "", **IMG, width=36), col("player_name", "Player"), col("position_group", "Pos"),
            col("role", "Role"), col("snap_pct", "Snap %", "integer", "0"), col("games", "G", "integer", "0"),
            col("offensive_epa", "Off. EPA", "float", "0.0"), col("ryoe_per_att", "RYOE/att", "float", "0.00"),
            col("separation_yds", "Separation", "float", "0.00"), col("yac_over_expected", "YAC OE", "float", "0.00"),
            col("sacks_plus_hits", "Sacks+hits", "float", "0.0"), col("sacks_hits_per_100", "Sk+hits /100", "float", "0.0"),
            col("pd_int_per_100", "PD+INT /100", "float", "0.0"), col("tackles_per_100", "Tkl /100", "float", "0.0")]),
         (0, 2, 12, 22)),
    ]),
    "draft": ("Draft", [
        (text("draft_head", "## Draft\nValue = PFR approximate value earned for the drafting team vs. the average at that pick "
                            "slot (picks within 4 slots, classes 5+ years old). Hit = 3+ seasons as a starter."), (0, 0, 12, 2)),
        (table("proj_table", "gm_draft_projection", "Projected first-round order if the season ended today", [
            col("projected_pick", "Pick", "integer", "0"), col("team_logo_url", "", **IMG, width=28), col("team_name", "Team"),
            col("record", "Record"), col("point_diff", "Pt diff", "integer", "0"), col("status", "")],
            "Ignores playoff results and traded picks."), (0, 2, 5, 20)),
        (bar("class_bar", "gm_draft_classes", "Our draft classes: AV above / below slot expectation", "draft_year",
             "surplus_av", "Surplus AV"), (5, 2, 7, 8)),
        (table("best_miss_table", "gm_draft_best_misses", "Best value and biggest misses, rounds 1-3, last 15 classes", [
            col("kind", ""), col("headshot_url", "", **IMG, width=30), col("player_name", "Player"), col("position", "Pos"),
            col("draft_year", "Year", "integer", "0"), col("round", "Rd", "integer", "0"), col("pick", "Pick", "integer", "0"),
            col("dr_av", "AV", "integer", "0"), col("expected_av", "Slot avg", "float", "0.0"),
            col("surplus_av", "Surplus", "float", "0.0"), col("seasons_started", "Seasons started", "integer", "0")]),
         (5, 10, 7, 12)),
        (table("pos_value_table", "gm_position_value", "League-wide: which positions pay off by round (since 2000)", [
            col("round", "Round", "integer", "0"), col("position", "Pos"), col("picks", "Picks", "integer", "0"),
            col("hit_rate_pct", "Hit rate %", "integer", "0"), col("pro_bowl_pct", "Pro Bowl %", "integer", "0"),
            col("avg_av", "Avg AV", "float", "0.0")]), (0, 22, 12, 10)),
    ]),
    "health": ("Health", [
        (text("health_head", "## Health\nLatest official injury report with each player's role and contract, and how many "
                             "starter-games each team has lost this season (weeks a starter was listed Out)."), (0, 0, 12, 2)),
        (table("inj_table", "gm_injuries", "Injury report", [
            col("headshot_url", "", **IMG, width=32), col("player_name", "Player"), col("position", "Pos"),
            col("status", "Status"), col("injury", "Injury"), col("role", "Role"), col("snap_pct", "Snap %", "integer", "0"),
            col("games_played", "GP", "integer", "0"), col("games_missed_injured", "Missed (inj.)", "integer", "0"),
            col("last_week_played", "Last played", "integer", "0"), col("apy_m", "APY $M", "float", "0.0"),
            col("week", "Week", "integer", "0")], "Includes players on injured reserve / PUP / NFI, which the official weekly report omits."),
         (0, 2, 12, 11)),
        (bar("inj_bar", "gm_injury_league", "League: starter-games lost to injury this season", "club",
             "starter_games_out", "Starter games out"), (0, 13, 12, 8)),
    ]),
}


def build() -> dict:
    ds = datasets()
    ds_names = {d["name"] for d in ds}
    with_team, out_pages = [], []
    for key, (title, layout) in LAYOUT.items():
        cells = set()
        for w, (x, y, wd, h) in layout:
            assert x + wd <= 12, (key, w["name"])
            for cx in range(x, x + wd):
                for cy in range(y, y + h):
                    assert (cx, cy) not in cells, (key, w["name"])
                    cells.add((cx, cy))
            for q in w.get("queries", []):
                assert q["query"]["datasetName"] in ds_names, q["query"]["datasetName"]
        out_pages.append({"name": key, "displayName": title, "pageType": "PAGE_TYPE_CANVAS",
                          "layout": [{"widget": w, "position": {"x": x, "y": y, "width": wd, "height": h}} for w, (x, y, wd, h) in layout]})
    for d in ds:
        sql = "".join(d["queryLines"])
        if re.search(r"\bteam\b", sql.split("FROM")[0]) and " AS club" not in sql:
            with_team.append(d["name"])
    out_pages.append({"name": "filters", "displayName": "Filters", "pageType": "PAGE_TYPE_GLOBAL_FILTERS",
                      "layout": [{"widget": team_filter(with_team), "position": {"x": 0, "y": 0, "width": 4, "height": 2}}]})
    return {"datasets": ds, "pages": out_pages,
            "uiSettings": {"theme": {"widgetHeaderAlignment": "ALIGNMENT_UNSPECIFIED"}, "applyModeEnabled": False}}


if __name__ == "__main__":
    dash = build()
    OUT.write_text(json.dumps(dash, indent=2) + "\n")
    team_ds = dash["pages"][-1]["layout"][0]["widget"]["queries"]
    print(f"wrote {OUT.name}: {len(dash['pages']) - 1} pages, {len(dash['datasets'])} datasets, "
          f"team filter bound to {[q['query']['datasetName'] for q in team_ds]}")
