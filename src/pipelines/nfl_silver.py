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
