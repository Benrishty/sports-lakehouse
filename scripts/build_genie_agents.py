"""Build the specialized GM Genie agents: genie/agents/<agent>/space.json (serialized_space v2).

    python scripts/build_genie_agents.py && python scripts/deploy_genie_agents.py

Each agent gets a focused set of tables (fewer tables = better SQL), column descriptions and synonyms,
shared accuracy rules plus domain rules, sample questions, and example SQL from genie/agents/examples.json
(every example was run against the real tables before it was added). IDs are content-derived, so rebuilding
without changes is a no-op update.
"""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "genie/agents"
EXAMPLES = json.loads((AGENTS_DIR / "examples.json").read_text())
T = "workspace.nfl."
OUR_TEAM = ("NYG", "New York Giants")  # who "we / our / us" means. Change here to re-point every agent.
NS = uuid.UUID("7a2e3b4c-0000-4000-8000-000000000000")


def hid(*parts) -> str:
    return uuid.uuid5(NS, "|".join(parts)).hex


def table(name, description, *columns):
    """columns: (name, description, synonyms, entity_match)"""
    cfgs = []
    for col, desc, syn, match in columns:
        c = {"column_name": col}
        if desc:
            c["description"] = [desc]
        if syn:
            c["synonyms"] = syn
        if match:
            c["enable_format_assistance"] = True
            c["enable_entity_matching"] = True
        cfgs.append(c)
    out = {"identifier": T + name, "description": [description]}
    if cfgs:
        out["column_configs"] = sorted(cfgs, key=lambda c: c["column_name"])
    return out


TEAM = ("team", "Franchise code, current code for every season (LA = Rams incl. St. Louis, LAC = Chargers incl. San Diego, LV = Raiders incl. Oakland).", ["club", "franchise"], True)
SEASON = ("season", "NFL season, labelled by the year it starts.", ["year"], False)
PLAYER = ("player_name", "Player full name exactly as stored, e.g. 'Brian Burns'.", ["player", "name"], True)

SHARED_RULES = [
    f"'We', 'us', 'our team' and 'my team' mean the {OUR_TEAM[1]} (team = '{OUR_TEAM[0]}') unless the user names another team.",
    "This is a general manager's assistant: lead with the answer, back it with the key numbers, and when relevant end with the decision it points to (e.g. extend, replace, target, draft). Keep it short.",
    "'This season' = the latest season in the data. Default to the regular season. Before answering about the current season, check gold_data_freshness if available and say 'as of week N'. PFR advanced stats (pressures, coverage allowed) lag weeks behind in-season: prefer play-by-play based columns for the current season and say so if you use PFR.",
    "Ranks are out of 32 teams: 1-8 = top tier, 9-16 = above average, 17-24 = below average, 25-32 = bottom tier. Use the tier words, never call a mid-table rank 'elite' or 'poor'.",
    "Use player and team names exactly as stored. Never expand an abbreviated name (e.g. 'J.Dart') into a guessed first name.",
    "Only state what the data shows. Injuries come only from the official injury report tables. The data has no trade rumors, coaching or scheme information: do not invent reasons.",
    "Money is in $ millions of APY (average annual value) from OverTheCap, not the exact current-year cap hit. Say 'APY' when quoting it.",
    "Round EPA to 3 decimals, rates to 1 decimal as percentages, money to 1 decimal.",
]

AGENTS = {
    "team_performance": {
        "title": "GM: Team Performance Analyst",
        "description": "Where is the team strong or weak, by phase and situation, versus the league? Report card ranks, situational efficiency (3rd down, red zone, pressure), play-action and blitz splits, standings and results.",
        "tables": [
            table("gold_team_report_card", "One row per team per season per metric with league rank, percentile and tier. The first place to look for strengths and weaknesses.",
                  SEASON, TEAM,
                  ("unit", "Offense, Defense, Special teams, Discipline or Overall. Filter on unit for 'our offense' / 'our defense' questions.", ["side of the ball"], True),
                  ("phase", "Sub-area within a unit, e.g. 'Pass rush', 'Situational D', 'Pass protection'.", None, True),
                  ("metric", "Metric name, e.g. 'Pressure rate (hits + sacks)'.", None, True),
                  ("better", "'higher', 'lower' (lower is better) or 'neutral' (a tendency, not a grade).", None, False),
                  ("league_rank", "Rank among 32 teams, 1 = best, direction-aware.", ["rank"], False),
                  ("tier", "top tier / above average / below average / bottom tier / tendency.", None, True)),
            table("gold_team_phase_stats", "Wide per-team, per-season, per-side (offense / defense) efficiency stats behind the report card, incl. red-zone trips.",
                  SEASON, TEAM, ("side", "'offense' = plays the team ran, 'defense' = plays it faced.", None, True)),
            table("gold_team_season", "Team season summary: record, net EPA and ranks, luck_gap (negative = unlucky).", SEASON, TEAM),
            table("gold_standings", "Division ranks and approximate playoff seeds (2002+), tiebreakers approximated by point differential.", SEASON, TEAM),
            table("gold_team_games", "Team game log: score, margin vs. spread, EPA per game.", SEASON, TEAM, ("opponent", "Opponent code.", None, True)),
            table("silver_plays", "Every play: use for situational drill-downs (down, distance, field position, play type). Scrimmage plays: is_pass = 1 OR is_rush = 1.",
                  SEASON, ("posteam", "Offense team code.", None, True), ("defteam", "Defense team code.", None, True)),
            table("silver_ftn_charting", "FTN charting per play (2022+): play action, RPO, screens, blitzers, pass rushers. Join silver_plays on game_id and play_id.", SEASON),
            table("gold_data_freshness", "How current each source is."),
        ],
        "rules": [
            "For 'weaknesses' / 'strengths' use gold_team_report_card, exclude better = 'neutral', and sort by league_rank.",
            "'Defense' / 'offense' questions mean the whole unit: filter unit = 'Defense' (or 'Offense'), never phase = 'Defense' alone, which misses pass rush, situational and takeaway metrics. Show the 3 worst metrics so the answer covers more than one.",
            "Compare to last season when the user asks about change or trend.",
        ],
        "samples": ["What are our three biggest weaknesses this season?", "How has our pass rush changed from last season?",
                    "How do we do in the red zone on offense and defense?", "Are we in playoff position right now?"],
    },
    "roster_cap": {
        "title": "GM: Roster & Cap Strategist",
        "description": "Who is worth their contract? Contract value vs. production within position group, expiring deals, spending by position vs. the league and top teams, and bargain targets on other rosters.",
        "tables": [
            table("gold_player_value", "Active contracts with current-season role and production. value_score = production percentile - cost percentile within position group: positive = bargain, negative = overpaid. OL and specialists are not scored.",
                  TEAM, PLAYER, ("position_group", "QB, RB, WR, TE, OL, IDL, EDGE, LB, CB, S, ST (contract positions).", ["position"], True),
                  ("apy_m", "Average annual value, $M.", ["salary", "contract", "cap"], False),
                  ("final_season", "Last season of the current contract. final_season <= season = expiring after this season.", ["contract end"], False),
                  ("value_score", "-1..1. Positive = outperforming the contract. Multiply by 100 for display.", ["value", "bargain", "overpaid"], False),
                  ("role", "starter (60%+ snaps) / rotation (25-60%) / reserve.", None, True)),
            table("gold_cap_allocation", "Spend by team and position group: share of team APY vs. league average and the 8 best teams by net EPA.", TEAM,
                  ("position_group", "Contract position group.", None, True)),
            table("silver_contracts", "Every OverTheCap contract (current and past): APY, guarantees, years, signing year. is_active = current deal.", PLAYER),
            table("gold_player_advanced", "Per-player season performance (box score, EPA, snaps, Next Gen Stats, defensive credit).", SEASON, PLAYER,
                  ("latest_team", "Team (franchise code).", ["team"], True)),
            table("gold_team_season", "Team season summary incl. net EPA rank.", SEASON, TEAM),
            table("gold_data_freshness", "How current each source is."),
        ],
        "rules": [
            "Keep two judgments separate: performance_tier = how good the player is (elite / very good / average / below average), contract_verdict = value for money (bargain / fair / overpaid). A 'fair' contract on an elite player means he is great AND paid like it, say both.",
            "Always mention production_basis (this season vs. last season when he has barely played) and availability (games_played, games_missed_injured, current_roster_status). Never call an injured player overpaid because he is not playing.",
            "Overpaid / bargain questions: use value_score / contract_verdict and show the rate it is based on (production_metric_name). OL and specialists are not scored.",
            "Trade or free-agent targets: players on OTHER teams with high value_score, ideally with final_season soon (cheaper to acquire) and age under 30.",
            "Spending questions: compare share_of_team_apy with league_avg_share and top8_avg_share.",
        ],
        "samples": ["Who are our most overpaid players right now?", "Which of our starters have contracts ending after this season?",
                    "How does our spending by position group compare to the top teams?", "Find edge rushers on other teams who are outperforming their contracts."],
    },
    "personnel": {
        "title": "GM: Personnel Scout",
        "description": "How good is each player, really? Box score, EPA, snap share, Next Gen Stats (separation, RYOE, YAC over expected, time to throw), defensive credit per snap, and the injury report.",
        "tables": [
            table("gold_player_advanced", "One row per player per season: box score, EPA, snap share and role, Next Gen Stats (2016+), PFR advanced (2018+, lags in-season) and play-by-play defensive credit per 100 snaps.",
                  SEASON, PLAYER, ("latest_team", "Team (franchise code).", ["team"], True),
                  ("position", "e.g. QB, RB, WR, TE, DE, DT, OLB, ILB, CB, SS, FS.", None, True),
                  ("position_group", "QB, RB, WR, TE, OL, DL, LB, DB, SPEC. Edge rushers can be DL (DE) or LB (OLB).", None, True),
                  ("avg_separation", "Next Gen Stats average separation from the nearest defender at the catch point, yards.", ["separation"], False),
                  ("rush_yards_over_expected_per_att", "Next Gen Stats rush yards over expected per carry.", ["RYOE"], False),
                  ("sacks_hits_per_100_snaps", "(Sacks + QB hits) per 100 defensive snaps, from play-by-play.", ["pressure rate", "pass rush"], False),
                  ("ball_production_per_100_snaps", "(Passes defensed + interceptions) per 100 defensive snaps.", ["coverage"], False)),
            table("gold_qb_season", "QB efficiency per season (min 100 dropbacks): EPA per dropback, CPOE.", SEASON, PLAYER),
            table("silver_player_week", "Weekly box scores: who played which week and how.", SEASON, PLAYER, ("team", "Team that week.", None, True)),
            table("gold_player_snaps_season", "Snap counts and role per player, season and team (2013+).", SEASON, TEAM, PLAYER),
            table("gold_injury_report", "Latest official injury report with each player's role and snap share.", TEAM, PLAYER,
                  ("status", "injured reserve, PUP, NFI (from roster status) or Out / Doubtful / Questionable / practice report only.", ["injury status"], True)),
            table("gold_data_freshness", "How current each source is."),
        ],
        "rules": [
            "Use sensible minimums so small samples don't top leaderboards: e.g. 50+ carries, 30+ targets, 150+ defensive snaps, 100+ dropbacks.",
            "Pass rushers: include both DL and LB position groups and rank by sacks_hits_per_100_snaps.",
        ],
        "samples": ["Which wide receivers create the most separation this season?", "Which pass rushers get to the quarterback most often per snap this season?",
                    "Who is on our injury report this week and how important are they?", "Which quarterbacks have played for us this season?"],
    },
    "draft": {
        "title": "GM: Draft & Development",
        "description": "How well do we draft and where do we pick? Pick value vs. slot expectation, team draft grades, position hit rates by round, combine results, and the projected draft order.",
        "tables": [
            table("gold_draft_pick_value", "Every pick since 2000 with career value for the drafting team (dr_av) vs. the slot average (expected_dr_av). surplus_av meaningful only when is_mature (5+ years since the draft). hit = 3+ seasons as a starter.",
                  TEAM, PLAYER, ("draft_year", "Draft class year.", ["class"], False), ("position", "PFR draft position, e.g. QB, T, DE, OLB, CB.", None, True)),
            table("gold_draft_team_grades", "Per team per mature class: picks, hits, Pro Bowlers, surplus AV vs. slot, class rank.", TEAM),
            table("gold_draft_position_value", "League-wide hit rate, Pro Bowl rate and average AV by position and round (mature classes since 2000).",
                  ("position", "PFR draft position.", None, True)),
            table("gold_draft_order_projection", "Projected first-round order if the season ended today (ignores playoffs and traded picks).", TEAM),
            table("silver_combine", "Scouting combine: 40, bench, vertical, broad, 3-cone, shuttle. Join gold_draft_pick_value on pfr_player_id.", PLAYER),
            table("gold_standings", "Current standings (drives the projected order).", SEASON, TEAM),
        ],
        "rules": [
            "Only grade classes where is_mature is true: recent classes have not had time to accumulate value. Say so if asked about a recent class.",
            "AV = Pro Football Reference approximate value earned for the drafting team (dr_av). Explain surplus as 'AV above/below what that pick slot usually produces'.",
            "The projected draft order ignores playoff results, tiebreakers and traded picks: say it is approximate.",
        ],
        "samples": ["Where are we projected to pick in the next draft?", "How have our draft classes performed over the last ten mature classes?",
                    "Which positions have the best hit rate in the first round?", "What were our best and worst draft picks since 2010?"],
    },
}


def build(key: str, spec: dict) -> dict:
    tables = spec["tables"]
    return {
        "version": 2,
        "config": {"sample_questions": sorted([{"id": hid(key, "q", q), "question": [q]} for q in spec["samples"]], key=lambda x: x["id"])},
        "data_sources": {"tables": sorted(tables, key=lambda t: t["identifier"])},
        "instructions": {
            "text_instructions": [{"id": hid(key, "ti"), "content": SHARED_RULES + spec["rules"]}],
            "example_question_sqls": sorted([{"id": hid(key, "ex", q), "question": [q], "sql": [sql]} for q, sql in EXAMPLES[key]],
                                            key=lambda x: x["id"]),
        },
    }


if __name__ == "__main__":
    for key, spec in AGENTS.items():
        out = AGENTS_DIR / key
        out.mkdir(parents=True, exist_ok=True)
        (out / "space.json").write_text(json.dumps(build(key, spec), indent=2, ensure_ascii=False) + "\n")
        (out / "meta.json").write_text(json.dumps({"title": spec["title"], "description": spec["description"]}, indent=2) + "\n")
        print(f"{key:18} {len(spec['tables'])} tables, {len(EXAMPLES[key])} examples -> {out.relative_to(ROOT)}/space.json")
