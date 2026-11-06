"""Build genie/nfl_genie_space.json, the Genie space definition (serialized_space v2).

    python scripts/build_genie_space.py
    ./scripts/deploy_genie.sh              # create the space, or update it if genie/space_id exists

Every example SQL here was run against the real tables before it was added. IDs are derived from the
content (uuid5), so rebuilding without changes produces an identical file and a no-op update.
"""
import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "genie/nfl_genie_space.json"
NS = uuid.UUID("6f1d2a3e-0000-4000-8000-000000000000")
T = "workspace.nfl."


def hid(*parts: str) -> str:
    return uuid.uuid5(NS, "|".join(parts)).hex


def cols(*specs):
    """(name, description, synonyms, match) -> column_configs entry."""
    out = []
    for name, desc, syn, match in specs:
        c = {"column_name": name}
        if desc:
            c["description"] = [desc]
        if syn:
            c["synonyms"] = syn
        if match:
            c["enable_format_assistance"] = True
            c["enable_entity_matching"] = True
        out.append(c)
    return sorted(out, key=lambda c: c["column_name"])


TEAM = ("team", "Franchise code, current code for every season (LA = Rams incl. St. Louis; LAC = Chargers incl. San Diego; LV = Raiders incl. Oakland).", ["club", "franchise"], True)
SEASON = ("season", "NFL season, labelled by the year it starts (the 2025 season includes Jan/Feb 2026 playoffs).", ["year"], False)

tables = [
    {
        "identifier": T + "gold_qb_season",
        "description": ["One row per quarterback per regular season, minimum 100 dropbacks."],
        "column_configs": cols(
            SEASON,
            ("player_name", "Quarterback full name, e.g. 'Josh Allen'. Use exactly as stored.", ["quarterback", "QB", "passer"], True),
            ("player_short_name", "Abbreviated name as in play-by-play, e.g. 'J.Allen'.", None, False),
            ("headshot_url", "Player headshot image URL.", None, False),
            ("latest_team", "Team the QB played for most recently that season.", ["team"], True),
            ("epa_per_dropback", "Average EPA per dropback. Higher is better; the main QB efficiency metric.", ["QB efficiency", "EPA/play"], False),
            ("cpoe", "Completion percentage over expected, in percentage points.", ["completion percentage over expected"], False),
            ("epa_rank", "Rank by epa_per_dropback within the season (1 = best).", None, False),
        ),
    },
    {
        "identifier": T + "gold_team_games",
        "description": ["One row per team per completed game (two rows per game): score, margin vs. the closing spread, and EPA efficiency."],
        "column_configs": cols(
            SEASON, TEAM,
            ("opponent", "Opponent franchise code.", None, True),
            ("game_type", "REG = regular season; WC, DIV, CON, SB = playoff rounds.", None, True),
            ("outcome", "W, L or T for this team.", ["result"], True),
            ("margin", "Points for minus points against.", ["point differential"], False),
            ("expected_margin", "Closing spread from this team's point of view: positive = favoured by that many points.", ["spread", "line"], False),
            ("cover_margin", "margin - expected_margin. Positive = beat the spread.", None, False),
            ("ats_outcome", "Result against the spread: cover, no cover or push.", ["against the spread", "ATS"], True),
            ("net_epa_per_play", "Offensive EPA/play minus defensive EPA/play allowed in this game. Higher is better.", ["net EPA"], False),
        ),
    },
    {
        "identifier": T + "gold_team_season",
        "description": ["One row per team per regular season: team name, conference, division, record, record against the spread, play-weighted EPA efficiency and league ranks."],
        "column_configs": cols(
            SEASON, TEAM,
            ("team_name", "Full team name, e.g. 'New York Giants'.", ["team name"], True),
            ("conference", "AFC or NFC.", None, True),
            ("division", "e.g. 'NFC East' (current alignment; valid from 2002).", None, True),
            ("off_epa_per_play", "Offensive EPA per scrimmage play. Higher is better.", ["offense", "offensive efficiency"], False),
            ("def_epa_per_play", "EPA per play allowed on defense. LOWER is better.", ["defense", "defensive efficiency"], False),
            ("net_epa_per_play", "off_epa_per_play - def_epa_per_play. Higher is better; the best single measure of team quality.", ["net EPA", "team efficiency"], False),
            ("net_epa_rank", "Rank by net_epa_per_play within the season (1 = best).", ["power ranking"], False),
            ("ats_covers", "Regular-season games where the team beat the closing spread.", ["covers"], False),
            ("pass_rate", "Share of scrimmage plays that were passes.", None, False),
            ("record_rank", "Rank by win percentage within the season (1 = best record; ties count half).", None, False),
            ("luck_gap", "net_epa_rank - record_rank. NEGATIVE = unlucky (plays better than its record). POSITIVE = lucky (record flatters it).", ["luck", "lucky", "unlucky", "overperforming", "underperforming"], False),
        ),
    },
    {
        "identifier": T + "gold_standings",
        "description": ["Standings per team per regular season since 2002: division rank, division leader, games back and an APPROXIMATE conference seed (division leaders seeds 1-4, then wild cards; ties broken by point differential, not official NFL tiebreakers). Use for every playoff / seeding / standings question."],
        "column_configs": cols(
            SEASON, TEAM,
            ("conference", "AFC or NFC.", None, True),
            ("division", "e.g. 'NFC East'.", None, True),
            ("division_rank", "Rank within the division (1 = leader).", None, False),
            ("division_leader", "True if the team currently leads its division (would host a playoff game as a top-4 seed).", ["division winner", "division lead"], False),
            ("division_games_back", "Games behind the division leader.", ["games back", "GB"], False),
            ("conference_seed", "Approximate playoff seed within the conference if the season ended today (1 = best).", ["seed", "playoff seed"], False),
            ("in_playoff_position", "True if conference_seed is within the playoff field (7 teams per conference from 2020, 6 before).", ["in the playoffs", "playoff spot"], False),
            ("win_pct", "(wins + 0.5 * ties) / games.", ["winning percentage"], False),
        ),
    },
    {
        "identifier": T + "gold_team_betting",
        "description": ["Betting records per team per regular season from closing lines: against the spread (overall, as favorite, as underdog, home, away) and over/under."],
        "column_configs": cols(
            SEASON, TEAM,
            ("ats_covers", "Games the team beat the closing spread.", ["covers", "ATS wins"], False),
            ("ats_losses", "Games the team failed to cover.", ["ATS losses"], False),
            ("ats_cover_pct", "Covers / (covers + ATS losses), pushes excluded.", ["cover rate", "ATS percentage"], False),
            ("favorite_covers", "Covers when favored.", None, False),
            ("underdog_covers", "Covers when the underdog.", None, False),
            ("outright_underdog_wins", "Straight-up wins as the underdog.", ["upsets"], False),
            ("overs", "Games where total points went over the closing total.", ["over"], False),
            ("unders", "Games where total points stayed under the closing total.", ["under"], False),
            ("over_pct", "Overs / (overs + unders), pushes excluded.", ["over rate", "O/U"], False),
            ("avg_total_vs_line", "Average (total points - closing total). Positive = games go over on average.", None, False),
        ),
    },
    {
        "identifier": T + "gold_player_season",
        "description": ["One row per player per regular season, 1999 to today: full name, position, team, headshot, passing / rushing / receiving / defensive / kicking totals, EPA and PPR fantasy points."],
        "column_configs": cols(
            SEASON,
            ("player_name", "Player full name, e.g. 'Jaxson Dart'. Use exactly as stored.", ["player", "name"], True),
            ("position", "e.g. QB, RB, WR, TE, LB, CB, K.", None, True),
            ("position_group", "e.g. QB, RB, WR, TE, DL, LB, DB, SPEC.", None, True),
            ("latest_team", "Team the player played for most recently that season (franchise code).", ["team"], True),
            ("headshot_url", "Player headshot image URL.", None, False),
            ("fantasy_points_ppr", "PPR fantasy points.", ["fantasy points"], False),
            ("fantasy_rank_in_position", "Rank by PPR fantasy points within position group and season.", None, False),
        ),
    },
    {
        "identifier": T + "silver_player_week",
        "description": ["One row per player per game week (REG and POST): box-score stats by week. Use for week-by-week player questions, e.g. who played QB for a team in which weeks."],
        "column_configs": cols(
            SEASON,
            ("player_name", "Player full name.", ["player"], True),
            ("team", "Player's team that week (franchise code).", None, True),
            ("opponent", "Opponent that week (franchise code).", None, True),
            ("position", "Position.", None, True),
            ("season_type", "REG or POST.", None, True),
            ("_snapshot_ts", None, None, False),
        ),
    },
    {
        "identifier": T + "silver_plays",
        "description": ["One row per play since 1999 (latest nflverse version). Use only for play-level questions; prefer the gold tables for team and QB aggregates."],
        "column_configs": cols(
            SEASON,
            ("posteam", "Team with the ball (franchise code).", ["offense team"], True),
            ("defteam", "Team on defense (franchise code).", ["defense team"], True),
            ("season_type", "REG or POST.", None, True),
            ("is_pass", "1 if a pass play (including sacks and scrambles).", None, False),
            ("is_rush", "1 if a designed run.", None, False),
            ("epa", "Expected points added on the play.", None, False),
            ("passer_player_name", "Passer, abbreviated name (e.g. 'B.Purdy').", ["quarterback"], True),
            ("receiver_player_name", "Targeted receiver, abbreviated name.", ["receiver", "target"], True),
            ("rusher_player_name", "Ball carrier on runs, abbreviated name.", ["running back", "rusher"], True),
            ("_snapshot_ts", None, None, False),
        ),
    },
]
for t in tables:  # hide the technical lineage column
    for c in t["column_configs"]:
        if c["column_name"] == "_snapshot_ts":
            c["exclude"] = True

INSTRUCTIONS = [
    "Data: NFL play-by-play and results from nflverse, 1999 to the current week, refreshed every Tuesday. 'This season' means the latest season in the data (MAX(season)).",
    "Default to the regular season (season_type = 'REG' / game_type = 'REG') unless the user asks about playoffs.",
    "Teams are stored as franchise codes, using the CURRENT code for all seasons: LA = Los Angeles Rams (also the St. Louis Rams), LAC = Chargers (also San Diego), LV = Raiders (also Oakland), WAS = Washington. Map team names, cities and nicknames to these codes.",
    "EPA = expected points added per play (nflverse model). Offense: higher is better. Defense (def_epa_per_play): LOWER is better. Net EPA = offense minus defense; higher is better. Success rate = share of plays with EPA > 0.",
    "Against the spread: cover_margin = margin - expected_margin; a positive cover_margin means the team beat the closing line.",
    "Luck: use the luck_gap column in gold_team_season, never recompute it. luck_gap = net_epa_rank - record_rank. UNLUCKY = most NEGATIVE luck_gap (plays better than its record): ORDER BY luck_gap ASC. LUCKY = most POSITIVE luck_gap (record better than its play): ORDER BY luck_gap DESC.",
    "Passing touchdowns: is_pass = 1 AND touchdown = 1 AND interception = 0 AND fumble_lost = 0. The touchdown flag alone also counts pick-sixes and fumble returns scored by the defense.",
    "Player names: use player_name exactly as stored (full names in gold_player_season, gold_qb_season, silver_player_week). Play-by-play names are abbreviated ('J.Dart'): NEVER expand an initial into a first name yourself; look the full name up in gold_player_season by player_id, or keep the abbreviation.",
    "Only state what the data shows. The data has no injury, trade, suspension or coaching information: if a player stops appearing, say 'has not played since week N' instead of giving a reason.",
    "Describe league ranks out of 32 teams honestly: 1-8 = top tier, 9-16 = above average, 17-24 = below average, 25-32 = bottom tier. Never call a rank in the teens 'elite' or 'poor'.",
    "Playoffs, seeds, standings and 'would they make the playoffs': ALWAYS use gold_standings (division leaders take seeds 1-4 even with a worse record than wild cards). Mention that tiebreakers are approximated by point differential.",
    "'Playing above expectation' / 'overperforming' = record better than play = POSITIVE luck_gap. 'Below expectation' = NEGATIVE luck_gap. Answer the question yes/no consistently with the sign.",
    "Betting questions (ATS, covers, over/under, favorites, underdogs) use gold_team_betting for season records and gold_team_games for individual games.",
    "Round EPA values to 3 decimals and percentages to 1 decimal.",
]

EXAMPLES = json.loads((Path(__file__).resolve().parent.parent / "genie/example_sql.json").read_text())

SAMPLE_QUESTIONS = [
    "Which teams have a .500 or worse record but a top-10 net EPA this season?",
    "Who are the top 10 quarterbacks by EPA per dropback this season?",
    "Which teams have the best record against the spread this season?",
    "Which team had the best offense each season since 1999?",
    "What does the NFC playoff picture look like right now?",
    "Who leads the league in receiving yards this season?",
]

space = {
    "version": 2,
    "config": {"sample_questions": sorted(
        [{"id": hid("q", q), "question": [q]} for q in SAMPLE_QUESTIONS], key=lambda x: x["id"])},
    "data_sources": {"tables": sorted(tables, key=lambda t: t["identifier"])},
    "instructions": {
        "text_instructions": [{"id": hid("ti"), "content": INSTRUCTIONS}],
        "example_question_sqls": sorted(
            [{"id": hid("ex", q), "question": [q], "sql": [sql]} for q, sql in EXAMPLES], key=lambda x: x["id"]),
        "join_specs": sorted([
            {"id": hid("join", left, right),
             "left": {"identifier": T + left, "alias": left},
             "right": {"identifier": T + right, "alias": right},
             "sql": [f"`{left}`.`season` = `{right}`.`season` AND `{left}`.`team` = `{right}`.`team`",
                     f"--rt=FROM_RELATIONSHIP_TYPE_{rel}--"]}
            for left, right, rel in [
                ("gold_team_games", "gold_team_season", "MANY_TO_ONE"),
                ("gold_standings", "gold_team_season", "ONE_TO_ONE"),
                ("gold_team_betting", "gold_team_season", "ONE_TO_ONE"),
            ]], key=lambda j: j["id"]),
    },
}

OUT.write_text(json.dumps(space, indent=2) + "\n")
print(f"wrote {OUT}: {len(tables)} tables, {len(EXAMPLES)} example SQLs, {len(SAMPLE_QUESTIONS)} sample questions")
