"""NFL silver layer (Lakeflow Spark Declarative Pipeline).

bronze_pbp holds every snapshot nflverse has published (the current season is re-landed each run),
so the same play appears many times. AUTO CDC keeps the newest version of each play, keyed on
(game_id, play_id) and ordered by the snapshot it came from. Same for games, keyed on game_id.

Known gap: a play nflverse *deletes* in a later snapshot stays in silver. Handling that needs a
snapshot diff (AUTO CDC FROM SNAPSHOT) and is listed as a next step in the README.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F

CATALOG = spark.conf.get("catalog")
SCHEMA = spark.conf.get("schema")
BRONZE_PBP = f"{CATALOG}.{SCHEMA}.bronze_pbp"
BRONZE_GAMES = f"{CATALOG}.{SCHEMA}.bronze_games"


# nflverse play-by-play uses each franchise's *current* code for every season (the 1999 Rams are LA),
# but the schedules file uses the historical code (STL). Map schedules onto the play-by-play convention so
# games join to plays; without this, ~50 team-seasons of STL/SD/OAK lose their record and per-game EPA.
# Other sources add PFR-style codes (GNB, KAN, ...) which map the same way; draft data is limited to 2000+,
# where STL can only mean the Rams.
FRANCHISE_CODE = {"STL": "LA", "SD": "LAC", "OAK": "LV", "LAR": "LA", "RAM": "LA", "RAI": "LV", "LVR": "LV",
                  "SDG": "LAC", "GNB": "GB", "KAN": "KC", "NOR": "NO", "NWE": "NE", "SFO": "SF", "TAM": "TB"}


def franchise(col: str):
    expr = F.col(col)
    for old, new in FRANCHISE_CODE.items():
        expr = F.when(F.col(col) == old, F.lit(new)).otherwise(expr)
    return expr.alias(col)


def flag(name: str):
    """nflverse 0/1 flags arrive as DOUBLE in bronze."""
    return F.col(name).cast("int").alias(name)


# ---------------------------------------------------------------- plays

@dp.temporary_view(comment="Typed, curated columns from bronze_pbp, one row per play per snapshot.")
@dp.expect_or_drop("has_key", "game_id IS NOT NULL AND play_id IS NOT NULL")
@dp.expect_or_drop("known_season_type", "season_type IN ('REG', 'POST')")
@dp.expect("epa_in_range", "epa IS NULL OR epa BETWEEN -15 AND 15")
@dp.expect("down_in_range", "down IS NULL OR down BETWEEN 1 AND 4")
def plays_typed():
    return spark.readStream.table(BRONZE_PBP).select(
        "game_id",
        F.col("play_id").cast("bigint").alias("play_id"),
        F.col("season").cast("int").alias("season"),
        "season_type",
        F.col("week").cast("int").alias("week"),
        F.to_date("game_date").alias("game_date"),
        "home_team",
        "away_team",
        "posteam",
        "defteam",
        F.col("qtr").cast("int").alias("qtr"),
        F.col("down").cast("int").alias("down"),
        F.col("ydstogo").cast("int").alias("ydstogo"),
        F.col("yardline_100").cast("int").alias("yardline_100"),
        F.col("game_seconds_remaining").cast("int").alias("game_seconds_remaining"),
        F.col("score_differential").cast("int").alias("score_differential"),
        "play_type",
        F.col("desc").alias("play_description"),
        F.col("yards_gained").cast("int").alias("yards_gained"),
        F.col("pass").cast("int").alias("is_pass"),
        F.col("rush").cast("int").alias("is_rush"),
        flag("qb_dropback"),
        flag("success"),
        flag("touchdown"),
        flag("interception"),
        flag("sack"),
        flag("fumble_lost"),
        flag("penalty"),
        "epa",
        "qb_epa",
        "wp",
        "wpa",
        "cpoe",
        "air_yards",
        "yards_after_catch",
        flag("qb_hit"),
        flag("first_down"),
        flag("third_down_converted"),
        flag("third_down_failed"),
        flag("fourth_down_converted"),
        flag("fourth_down_failed"),
        flag("goal_to_go"),
        flag("shotgun"),
        flag("no_huddle"),
        F.col("fixed_drive").cast("int").alias("drive_id"),
        F.col("fixed_drive_result").alias("drive_result"),
        "penalty_team",
        F.col("penalty_yards").cast("int").alias("penalty_yards"),
        "pass_length",
        "pass_location",
        "run_location",
        "run_gap",
        "xpass",
        "pass_oe",
        "field_goal_result",
        F.col("kick_distance").cast("int").alias("kick_distance"),
        # defensive credit (gsis ids): who sacked / hit the QB, defended or intercepted the pass
        "sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id",
        "qb_hit_1_player_id", "qb_hit_2_player_id",
        "pass_defense_1_player_id", "pass_defense_2_player_id", "interception_player_id",
        # `id`/`name` = the dropback player (passer, or the QB on a scramble/sack)
        F.col("id").alias("dropback_player_id"),
        F.col("name").alias("dropback_player_name"),
        "passer_player_id",
        "passer_player_name",
        "rusher_player_id",
        "rusher_player_name",
        "receiver_player_id",
        "receiver_player_name",
        "_snapshot_ts",
    )


dp.create_streaming_table(
    name="silver_plays",
    comment="One row per NFL play (latest nflverse version), 1999 → today. SCD type 1.",
    cluster_by=["season", "week"],
)

dp.create_auto_cdc_flow(
    target="silver_plays",
    source="plays_typed",
    keys=["game_id", "play_id"],
    sequence_by=F.col("_snapshot_ts"),
    stored_as_scd_type=1,
)


# ---------------------------------------------------------------- games

@dp.temporary_view(comment="Typed schedule/results/betting lines from bronze_games.")
@dp.expect_or_drop("has_key", "game_id IS NOT NULL")
def games_typed():
    return spark.readStream.table(BRONZE_GAMES).select(
        "game_id",
        F.col("season").cast("int").alias("season"),
        "game_type",
        F.col("week").cast("int").alias("week"),
        F.to_date("gameday").alias("game_date"),
        franchise("home_team"),
        franchise("away_team"),
        F.col("home_score").cast("int").alias("home_score"),
        F.col("away_score").cast("int").alias("away_score"),
        # result = home_score - away_score; spread_line > 0 means the home team is favoured
        F.col("result").cast("int").alias("result"),
        "spread_line",
        "total_line",
        F.col("div_game").cast("int").alias("div_game"),
        "roof",
        "surface",
        F.col("home_rest").cast("int").alias("home_rest"),
        F.col("away_rest").cast("int").alias("away_rest"),
        "_snapshot_ts",
    )


dp.create_streaming_table(
    name="silver_games",
    comment="One row per NFL game with result and closing spread/total. SCD type 1.",
)

dp.create_auto_cdc_flow(
    target="silver_games",
    source="games_typed",
    keys=["game_id"],
    sequence_by=F.col("_snapshot_ts"),
    stored_as_scd_type=1,
)


# ---------------------------------------------------------------- teams (dimension)
BRONZE_TEAMS = f"{CATALOG}.{SCHEMA}.bronze_teams"
BRONZE_PLAYERS = f"{CATALOG}.{SCHEMA}.bronze_players"
BRONZE_PLAYER_WEEK = f"{CATALOG}.{SCHEMA}.bronze_player_week"


@dp.temporary_view(comment="Team names, conference/division, colours and logo URLs from nflverse.")
@dp.expect_or_drop("has_key", "team IS NOT NULL")
def teams_typed():
    return spark.readStream.table(BRONZE_TEAMS).select(
        F.col("team_abbr").alias("team"),
        "team_name",
        F.col("team_nick").alias("team_nickname"),
        F.col("team_conf").alias("conference"),
        F.col("team_division").alias("division"),
        F.col("team_color").alias("team_color"),
        F.col("team_color2").alias("team_color2"),
        F.col("team_logo_espn").alias("team_logo_url"),
        F.col("team_wordmark").alias("team_wordmark_url"),
        "_snapshot_ts",
    )


dp.create_streaming_table(
    name="silver_teams",
    comment="One row per team code (current and historical codes), with conference, division (current alignment), colours and logo URLs.",
)
dp.create_auto_cdc_flow(target="silver_teams", source="teams_typed", keys=["team"],
                        sequence_by=F.col("_snapshot_ts"), stored_as_scd_type=1)


# ---------------------------------------------------------------- players (dimension)

@dp.temporary_view(comment="Player bio, position and headshot URL from nflverse players.")
@dp.expect_or_drop("has_key", "player_id IS NOT NULL")
def players_typed():
    return spark.readStream.table(BRONZE_PLAYERS).select(
        F.col("gsis_id").alias("player_id"),
        F.col("display_name").alias("player_name"),
        "first_name",
        "last_name",
        F.col("short_name").alias("player_short_name"),
        "position",
        "position_group",
        F.col("headshot").alias("headshot_url"),
        F.col("height").cast("int").alias("height_in"),
        F.col("weight").cast("int").alias("weight_lb"),
        F.to_date("birth_date").alias("birth_date"),
        F.col("college_name").alias("college"),
        F.col("rookie_season").cast("int").alias("rookie_season"),
        F.col("draft_year").cast("int").alias("draft_year"),
        F.col("draft_round").cast("int").alias("draft_round"),
        F.col("draft_pick").cast("int").alias("draft_pick"),
        "latest_team",
        "status",
        F.col("years_of_experience").cast("int").alias("years_of_experience"),
        "jersey_number",
        # crosswalk ids: PFR (snap counts, PFR advanced stats), OverTheCap (contracts), ESPN
        "pfr_id",
        F.col("otc_id").cast("string").alias("otc_id"),
        "espn_id",
        "_snapshot_ts",
    )


dp.create_streaming_table(
    name="silver_players",
    comment="One row per player (nflverse gsis id): full name, position, bio, draft and headshot URL.",
)
dp.create_auto_cdc_flow(target="silver_players", source="players_typed", keys=["player_id"],
                        sequence_by=F.col("_snapshot_ts"), stored_as_scd_type=1)


# ---------------------------------------------------------------- player × week stats

def i(name: str, alias: str = None):
    return F.col(name).cast("int").alias(alias or name)


@dp.temporary_view(comment="Typed weekly player box-score stats, one row per player per game week per snapshot.")
@dp.expect_or_drop("has_key", "player_id IS NOT NULL AND season IS NOT NULL AND week IS NOT NULL")
@dp.expect("known_season_type", "season_type IN ('REG', 'POST')")
def player_week_typed():
    return spark.readStream.table(BRONZE_PLAYER_WEEK).select(
        "player_id",
        F.col("player_display_name").alias("player_name"),
        F.col("player_name").alias("player_short_name"),
        "position",
        "position_group",
        "headshot_url",
        i("season"), i("week"), "season_type", "game_id",
        "team",
        F.col("opponent_team").alias("opponent"),
        # passing
        i("completions"), i("attempts"), i("passing_yards"), i("passing_tds"),
        i("passing_interceptions"), i("sacks_suffered"), "passing_epa", "passing_cpoe",
        # rushing
        i("carries"), i("rushing_yards"), i("rushing_tds"), "rushing_epa",
        # receiving
        i("receptions"), i("targets"), i("receiving_yards"), i("receiving_tds"), "receiving_epa",
        "target_share", "air_yards_share",
        # defense
        i("def_tackles_solo"), i("def_tackle_assists"), "def_sacks", i("def_interceptions"), i("def_tds"),
        # kicking
        i("fg_made"), i("fg_att"),
        "fantasy_points", "fantasy_points_ppr",
        "_snapshot_ts",
    )


dp.create_streaming_table(
    name="silver_player_week",
    comment="One row per player per week (REG and POST), 1999 → today: passing, rushing, receiving, defense, kicking, fantasy.",
    cluster_by=["season", "week"],
)
dp.create_auto_cdc_flow(target="silver_player_week", source="player_week_typed",
                        keys=["player_id", "season", "week", "season_type"],
                        sequence_by=F.col("_snapshot_ts"), stored_as_scd_type=1)


# ================================================================ front-office and advanced datasets
#
# Seasonal feeds (snap counts, injuries, FTN charting) keep the AUTO CDC pattern. Whole-file feeds
# (contracts, draft, combine, Next Gen Stats, PFR advanced) are re-published in full with no stable key,
# so their silver tables are materialized views over the LATEST bronze snapshot: simple, and rows that
# nflverse removes disappear too.

def latest_snapshot(table: str):
    df = spark.read.table(table)
    newest = df.agg(F.max("_snapshot_ts").alias("_newest"))
    return df.join(newest, F.col("_snapshot_ts") == F.col("_newest")).drop("_newest")


def bronze(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.bronze_{name}"


# ---------------------------------------------------------------- snap counts (2012+)

@dp.temporary_view()
@dp.expect_or_drop("has_key", "pfr_player_id IS NOT NULL AND game_id IS NOT NULL")
def snap_counts_typed():
    return spark.readStream.table(bronze("snap_counts")).select(
        "game_id", i("season"), "game_type", i("week"),
        F.col("player").alias("player_name"), "pfr_player_id", "position",
        franchise("team"), franchise("opponent"),
        i("offense_snaps"), "offense_pct", i("defense_snaps"), "defense_pct", i("st_snaps"), "st_pct",
        "_snapshot_ts",
    )


dp.create_streaming_table(name="silver_snap_counts",
                          comment="One row per player per game, 2012+: offense / defense / special-teams snaps and snap share (PFR ids).",
                          cluster_by=["season", "week"])
dp.create_auto_cdc_flow(target="silver_snap_counts", source="snap_counts_typed", keys=["pfr_player_id", "game_id"],
                        sequence_by=F.col("_snapshot_ts"), stored_as_scd_type=1)


# ---------------------------------------------------------------- injury reports (2009+)

@dp.temporary_view()
@dp.expect_or_drop("has_key", "player_id IS NOT NULL AND season IS NOT NULL AND week IS NOT NULL AND team IS NOT NULL")
def injuries_typed():
    return spark.readStream.table(bronze("injuries")).select(
        i("season"), "season_type", "game_type", franchise("team"), i("week"),
        F.col("gsis_id").alias("player_id"), F.col("full_name").alias("player_name"), "position",
        "report_status", "report_primary_injury", "report_secondary_injury",
        "practice_status", "practice_primary_injury",
        "_snapshot_ts",
    )


dp.create_streaming_table(name="silver_injuries",
                          comment="Official weekly injury report, 2009+: game status (Out / Doubtful / Questionable), injury, practice participation.")
dp.create_auto_cdc_flow(target="silver_injuries", source="injuries_typed",
                        keys=["season", "week", "game_type", "team", "player_id"],
                        sequence_by=F.col("_snapshot_ts"), stored_as_scd_type=1)


# ---------------------------------------------------------------- weekly roster status (2002+)

@dp.temporary_view()
@dp.expect_or_drop("has_key", "player_id IS NOT NULL AND season IS NOT NULL AND week IS NOT NULL AND team IS NOT NULL")
def roster_week_typed():
    return (spark.readStream.table(bronze("roster_week")).select(
        i("season"), i("week"), "game_type", franchise("team"), F.col("gsis_id").alias("player_id"),
        F.col("full_name").alias("player_name"), "position", "depth_chart_position",
        F.col("status").alias("roster_status"), F.col("status_description_abbr").alias("status_code"),
        # readable availability: R01 / R48 = injured reserve (R48 = designated to return), R04 = PUP, R05 = NFI
        F.when(F.col("status_description_abbr").isin("R01", "R48"), "injured reserve")
         .when(F.col("status_description_abbr") == "R04", "PUP")
         .when(F.col("status_description_abbr") == "R05", "NFI")
         .when(F.col("status") == "RES", "reserve (other)")
         .when(F.col("status") == "ACT", "active")
         .when(F.col("status") == "INA", "inactive")
         .when(F.col("status") == "DEV", "practice squad")
         .otherwise(F.lower(F.col("status"))).alias("availability"),
        "_snapshot_ts",
    ).dropDuplicates(["season", "week", "game_type", "team", "player_id", "_snapshot_ts"]))


dp.create_streaming_table(name="silver_roster_week",
                          comment="Weekly roster status per player and team, 2002+: active, inactive, injured reserve, PUP, NFI, practice squad. "
                                  "The official injury report omits players on injured reserve, so use this for availability.",
                          cluster_by=["season", "week"])
dp.create_auto_cdc_flow(target="silver_roster_week", source="roster_week_typed",
                        keys=["season", "week", "game_type", "team", "player_id"],
                        sequence_by=F.col("_snapshot_ts"), stored_as_scd_type=1)


# ---------------------------------------------------------------- FTN charting (2022+)

FTN_FLAGS = ["is_no_huddle", "is_motion", "is_play_action", "is_screen_pass", "is_rpo", "is_trick_play",
             "is_qb_out_of_pocket", "is_interception_worthy", "is_throw_away", "is_catchable_ball",
             "is_contested_ball", "is_created_reception", "is_drop", "is_qb_sneak", "is_qb_fault_sack"]


@dp.temporary_view()
@dp.expect_or_drop("has_key", "game_id IS NOT NULL AND play_id IS NOT NULL")
def ftn_typed():
    return spark.readStream.table(bronze("ftn_charting")).select(
        F.col("nflverse_game_id").alias("game_id"), F.col("nflverse_play_id").cast("bigint").alias("play_id"),
        i("season"), i("week"), "qb_location",
        i("n_offense_backfield"), i("n_defense_box"), i("n_blitzers"), i("n_pass_rushers"),
        *[F.col(c).cast("boolean").alias(c) for c in FTN_FLAGS],
        "_snapshot_ts",
    )


dp.create_streaming_table(name="silver_ftn_charting",
                          comment="FTN charting per play, 2022+: play action, RPO, screens, motion, blitzers, pass rushers, box count, drops, catchable / contested balls. Joins silver_plays on (game_id, play_id).")
dp.create_auto_cdc_flow(target="silver_ftn_charting", source="ftn_typed", keys=["game_id", "play_id"],
                        sequence_by=F.col("_snapshot_ts"), stored_as_scd_type=1)


# ---------------------------------------------------------------- contracts (OverTheCap)

@dp.materialized_view(comment="Every NFL contract tracked by OverTheCap (latest snapshot). is_active = the player's current deal. "
                              "APY = average annual value; apy_cap_pct = APY as a share of the salary cap in the signing year.")
@dp.expect("has_player", "player_id IS NOT NULL")
def silver_contracts():
    return latest_snapshot(bronze("contracts")).select(
        F.col("gsis_id").alias("player_id"), F.col("otc_id").cast("bigint").cast("string").alias("otc_id"),
        F.col("player").alias("player_name"), "position", F.col("team").alias("team_raw"),
        F.col("is_active").cast("boolean").alias("is_active"),
        i("year_signed"), F.col("years").cast("int").alias("contract_years"),
        (F.col("year_signed") + F.col("years") - 1).cast("int").alias("final_season"),
        F.col("value").alias("total_value_m"), F.col("apy").alias("apy_m"), F.col("guaranteed").alias("guaranteed_m"),
        "apy_cap_pct", F.col("inflated_apy").alias("inflated_apy_m"),
        i("draft_year"), i("draft_round"), i("draft_overall"), F.col("draft_team").alias("draft_team_raw"),
    )


# ---------------------------------------------------------------- draft picks (2000+) and combine

@dp.materialized_view(comment="Every draft pick since 2000 with career outcome: games, starts, Pro Bowls, All-Pros and PFR approximate value "
                              "(w_av = weighted career AV, dr_av = AV earned for the drafting team).")
@dp.expect_or_drop("modern_era", "draft_year >= 2000")
def silver_draft_picks():
    return latest_snapshot(bronze("draft_picks")).select(
        i("season", "draft_year"), i("round"), i("pick"), franchise("team"),
        F.col("gsis_id").alias("player_id"), "pfr_player_id", F.col("pfr_player_name").alias("player_name"),
        "position", "category", "side", "college", i("age"),
        F.col("to").cast("int").alias("last_season"),
        F.col("hof").cast("boolean").alias("hall_of_fame"), i("allpro"), i("probowls"), i("seasons_started"),
        i("w_av"), i("dr_av"), i("games"),
    )


@dp.materialized_view(comment="NFL Scouting Combine results, 2000+: 40-yard dash, bench, vertical, broad jump, 3-cone, shuttle.")
def silver_combine():
    return latest_snapshot(bronze("combine")).select(
        i("season"), i("draft_year"), F.col("draft_team").alias("draft_team_name"), i("draft_round"), i("draft_ovr", "draft_overall"),
        F.col("pfr_id").alias("pfr_player_id"), "player_name", F.col("pos").alias("position"), F.col("school").alias("college"),
        F.col("ht").alias("height"), F.col("wt").cast("int").alias("weight_lb"),
        "forty", i("bench"), "vertical", i("broad_jump"), "cone", "shuttle",
    )


# ---------------------------------------------------------------- Next Gen Stats (2016+), week 0 = season

def ngs(kind: str, *cols):
    return latest_snapshot(bronze(f"ngs_{kind}")).select(
        i("season"), "season_type", i("week"), F.col("player_gsis_id").alias("player_id"),
        F.col("player_display_name").alias("player_name"), F.col("player_position").alias("position"),
        franchise("team_abbr").alias("team"), *cols)


@dp.materialized_view(comment="Next Gen Stats passing by player-week (week 0 = full season): time to throw, aggressiveness, air yards, CPOE.")
def silver_ngs_passing():
    return ngs("passing", "avg_time_to_throw", "aggressiveness", "avg_intended_air_yards", "avg_completed_air_yards",
               "avg_air_yards_to_sticks", "completion_percentage", "expected_completion_percentage",
               "completion_percentage_above_expectation", "passer_rating", i("attempts"), i("pass_yards"))


@dp.materialized_view(comment="Next Gen Stats rushing by player-week (week 0 = full season): rush yards over expected (RYOE), stacked boxes, time to line.")
def silver_ngs_rushing():
    return ngs("rushing", i("rush_attempts"), i("rush_yards"), "expected_rush_yards", "rush_yards_over_expected",
               "rush_yards_over_expected_per_att", "rush_pct_over_expected", "percent_attempts_gte_eight_defenders",
               "avg_time_to_los", "efficiency")


@dp.materialized_view(comment="Next Gen Stats receiving by player-week (week 0 = full season): separation, cushion, YAC over expected, share of team air yards.")
def silver_ngs_receiving():
    return ngs("receiving", i("targets"), i("receptions"), i("yards"), "avg_separation", "avg_cushion",
               "avg_intended_air_yards", "percent_share_of_intended_air_yards", "catch_percentage",
               "avg_yac", "avg_expected_yac", "avg_yac_above_expectation")


# ---------------------------------------------------------------- Pro Football Reference advanced (2018+, season level)

def pfr(kind: str, team_col: str, *cols):
    return latest_snapshot(bronze(f"pfr_{kind}")).select(
        i("season"), F.col("pfr_id").alias("pfr_player_id"), F.col("player").alias("player_name"),
        franchise(team_col).alias("team"), *cols)


@dp.materialized_view(comment="PFR advanced defense per player-season: pressures, hurries, QB knockdowns, sacks, blitzes, missed tackles, "
                              "and coverage allowed (targets, completions, yards, TDs, passer rating). team = '2TM'/'3TM' for multi-team seasons.")
def silver_pfr_defense():
    return pfr("def", "tm", F.col("pos").alias("position"), i("g", "games"), i("gs", "games_started"),
               i("prss", "pressures"), i("hrry", "hurries"), i("qbkd", "qb_knockdowns"), F.col("sk").alias("sacks"),
               i("bltz", "blitzes"), i("comb", "tackles"), i("m_tkl", "missed_tackles"),
               F.col("m_tkl_percent").alias("missed_tackle_pct"),
               i("tgt", "targets_allowed"), i("cmp", "completions_allowed"), F.col("cmp_percent").alias("completion_pct_allowed"),
               i("yds", "yards_allowed"), i("td", "tds_allowed"), i("int", "interceptions"),
               F.col("rat").alias("passer_rating_allowed"), F.col("dadot").alias("adot_allowed"))


@dp.materialized_view(comment="PFR advanced passing per QB-season: pressure rate, time in pocket, bad throws, drops, play action, RPO, scrambles.")
def silver_pfr_passing():
    return pfr("pass", "team", i("pass_attempts"), i("times_pressured"), "pressure_pct", "pocket_time",
               i("times_blitzed"), i("times_hurried"), i("times_hit"), "bad_throw_pct", "on_tgt_pct", "drop_pct",
               i("pa_pass_att", "play_action_attempts"), i("pa_pass_yards", "play_action_yards"),
               i("rpo_plays"), i("scrambles"))


@dp.materialized_view(comment="PFR advanced rushing per player-season: yards before / after contact, broken tackles.")
def silver_pfr_rushing():
    return pfr("rush", "tm", F.col("pos").alias("position"), i("att", "attempts"), i("yds", "yards"),
               "ybc_att", "yac_att", i("brk_tkl", "broken_tackles"), "att_br")


@dp.materialized_view(comment="PFR advanced receiving per player-season: drops, broken tackles, aDOT, yards after catch, passer rating when targeted.")
def silver_pfr_receiving():
    return pfr("rec", "tm", F.col("pos").alias("position"), i("tgt", "targets"), i("rec", "receptions"), i("yds", "yards"),
               "adot", "yac_r", i("brk_tkl", "broken_tackles"), i("drop", "drops"), F.col("drop_percent").alias("drop_pct"),
               F.col("rat").alias("passer_rating_when_targeted"))
