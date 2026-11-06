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
FRANCHISE_CODE = {"STL": "LA", "SD": "LAC", "OAK": "LV"}


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
