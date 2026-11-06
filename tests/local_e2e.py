"""Local end-to-end check (no Databricks needed) of the NFL lakehouse code on real nflverse files.

bronze: real apply_bronze_contract from the notebook, two snapshots of 2026 (second one edited)
silver: real select logic from nfl_silver.py, with decorators stubbed; expectations applied as filters;
        AUTO CDC SCD1 emulated as "latest _snapshot_ts per key"
gold:   real nfl_gold.sql, each MV created as a temp view

Run:
  pip install "pyspark>=4.0"          # needs Java 17+
  ./scripts/fetch_test_data.sh tests/data
  python tests/local_e2e.py . tests/data
"""
import ast, datetime as dt, re, sys, types
from pathlib import Path

from pyspark.sql import SparkSession, DataFrame, Window, functions as F, types as T

PROJ = Path(sys.argv[1])
DATA = Path(sys.argv[2])
spark = SparkSession.builder.master("local[4]").config("spark.sql.shuffle.partitions", "8") \
    .config("spark.driver.memory", "8g").getOrCreate()
spark.sparkContext.setLogLevel("ERROR")

# ---- bronze: pull real functions out of the notebook source
src = (PROJ / "src/ingest/nfl_ingest.py").read_text()
mod = ast.parse(src)
ns = {"F": F, "T": T, "DataFrame": DataFrame, "dt": dt, "re": re, "FIRST_SEASON": 1999}
for node in mod.body:
    if isinstance(node, ast.FunctionDef) and node.name in {"apply_bronze_contract", "snapshot_ts", "current_nfl_season", "resolve_seasons"}:
        exec(compile(ast.Module([node], []), "nb", "exec"), ns)

assert ns["current_nfl_season"](dt.date(2026, 11, 6)) == 2026
assert ns["current_nfl_season"](dt.date(2027, 2, 1)) == 2026
assert ns["resolve_seasons"]("backfill", dt.date(2026, 11, 6))[:2] == [1999, 2000]
assert ns["resolve_seasons"]("2023, 2024", dt.date(2026, 11, 6)) == [2023, 2024]

def bronze(path: Path, snap: str, mutate=None) -> DataFrame:
    p = f"/Volumes/x/y/landing/nfl/pbp/snapshot={snap}/{path.name}"
    df = ns["apply_bronze_contract"](spark.read.parquet(str(path)))
    if mutate: df = mutate(df)
    return (df.withColumn("_source_file", F.lit(p))
              .withColumn("_snapshot_ts", F.lit(ns["snapshot_ts"](p)).cast("timestamp")))

parts = [bronze(DATA / f"play_by_play_{y}.parquet", "20261101T000000Z") for y in (1999, 2010, 2020, 2025, 2026)]
# second, later snapshot of 2026 where nflverse "corrected" one play's EPA
first_key = parts[-1].select("game_id", "play_id").where("epa IS NOT NULL AND pass = 1").first()
parts.append(bronze(DATA / "play_by_play_2026.parquet", "20261106T120000Z",
                    lambda d: d.withColumn("epa", F.when((F.col("game_id") == first_key.game_id) & (F.col("play_id") == first_key.play_id), F.lit(9.99)).otherwise(F.col("epa")))))

# every file must have an identical schema after the contract, or Delta append would fail
schemas = {str(p.drop("_source_file", "_snapshot_ts").schema) for p in parts}
assert len(schemas) == 1, "bronze contract does not unify schemas across seasons"
bronze_pbp = parts[0]
for p in parts[1:]: bronze_pbp = bronze_pbp.unionByName(p)
games_p = "/Volumes/x/y/landing/nfl/games/snapshot=20261106T120000Z/games.parquet"
bronze_games = ns["apply_bronze_contract"](spark.read.parquet(str(DATA / "games.parquet"))) \
    .withColumn("_snapshot_ts", F.lit(ns["snapshot_ts"](games_p)).cast("timestamp"))
def bronze_file(name: str, ds: str):
    p = f"/Volumes/x/y/landing/nfl/{ds}/snapshot=20261106T120000Z/{name}"
    return ns["apply_bronze_contract"](spark.read.parquet(str(DATA / name))) \
        .withColumn("_snapshot_ts", F.lit(ns["snapshot_ts"](p)).cast("timestamp"))

# every other bronze table: sample files per dataset (seasonal datasets get an old and a current season)
BRONZE_FILES = {
    "teams": ["teams_colors_logos.parquet"], "players": ["players.parquet"],
    "player_week": ["stats_player_week_1999.parquet", "stats_player_week_2025.parquet", "stats_player_week_2026.parquet"],
    "snap_counts": ["snap_counts_2015.parquet", "snap_counts_2025.parquet", "snap_counts_2026.parquet"],
    "injuries": ["injuries_2012.parquet", "injuries_2025.parquet", "injuries_2026.parquet"],
    "roster_week": ["roster_weekly_2015.parquet", "roster_weekly_2026.parquet"],
    "ftn_charting": ["ftn_charting_2022.parquet", "ftn_charting_2026.parquet"],
    "contracts": ["historical_contracts.parquet"], "draft_picks": ["draft_picks.parquet"], "combine": ["combine.parquet"],
    "ngs_passing": ["ngs_passing.parquet"], "ngs_rushing": ["ngs_rushing.parquet"], "ngs_receiving": ["ngs_receiving.parquet"],
    "pfr_def": ["advstats_season_def.parquet"], "pfr_pass": ["advstats_season_pass.parquet"],
    "pfr_rush": ["advstats_season_rush.parquet"], "pfr_rec": ["advstats_season_rec.parquet"],
}
BRONZE = {"x.y.bronze_pbp": bronze_pbp, "x.y.bronze_games": bronze_games}
for ds, files in BRONZE_FILES.items():
    df = None
    for f in files:
        part = bronze_file(f, ds)
        df = part if df is None else df.unionByName(part, allowMissingColumns=True)
    BRONZE[f"x.y.bronze_{ds}"] = df
print("bronze_pbp rows", bronze_pbp.count())

# ---- silver: exec the pipeline file with a stub dp module
views, expects, cdc = {}, {}, []
def temporary_view(fn=None, **kw):
    def deco(f):
        views[f.__name__] = f; return f
    return deco(fn) if fn else deco
def expect_factory(kind):
    def expect(name, cond):
        def deco(f):
            expects.setdefault(f.__name__, []).append((kind, name, cond)); return f
        return deco
    return expect
mvs = []
def materialized_view(fn=None, **kw):
    def deco(f):
        mvs.append(f); return f
    return deco(fn) if fn else deco
dp = types.SimpleNamespace(temporary_view=temporary_view, materialized_view=materialized_view, expect=expect_factory("warn"),
    expect_or_drop=expect_factory("drop"), create_streaming_table=lambda **kw: None,
    create_auto_cdc_flow=lambda **kw: cdc.append(kw))
fake_pkg = types.ModuleType("pyspark_stub"); fake_pkg.pipelines = dp

class StubSpark:
    conf = types.SimpleNamespace(get=lambda k: {"catalog": "x", "schema": "y"}[k])
    class readStream:  # noqa: N801
        @staticmethod
        def table(name):
            return BRONZE[name]
    read = readStream

silver_src = (PROJ / "src/pipelines/nfl_silver.py").read_text().replace(
    "from pyspark import pipelines as dp", "dp = __dp__")
exec(silver_src, {"__dp__": dp, "spark": StubSpark, "__name__": "silver"})

for flow in cdc:
    view = flow["source"]
    df = views[view]()
    for kind, name, cond in expects.get(view, []):
        bad = df.where(f"NOT ({cond})").count()
        print(f"  expectation {view}.{name} [{kind}] violations={bad}")
        if kind == "drop": df = df.where(cond)
    w = Window.partitionBy(*flow["keys"]).orderBy(F.col("_snapshot_ts").desc())
    out = df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")
    out = out.localCheckpoint()  # materialize like the pipeline does, so query plans stay small
    out.createOrReplaceTempView(flow["target"])
    print(flow["target"], out.count())

for f in mvs:  # silver materialized views (latest-snapshot feeds); expectations applied like the pipeline does
    df = f()
    for kind, name, cond in expects.get(f.__name__, []):
        bad = df.where(f"NOT ({cond})").count()
        print(f"  expectation {f.__name__}.{name} [{kind}] violations={bad}")
        if kind == "drop": df = df.where(cond)
    df = df.localCheckpoint()
    df.createOrReplaceTempView(f.__name__)
    print(f.__name__, df.count())

# dedup check: latest snapshot wins
v = spark.sql(f"select epa from silver_plays where game_id='{first_key.game_id}' and play_id={int(first_key.play_id)}").collect()
assert len(v) == 1 and abs(v[0].epa - 9.99) < 1e-9, v
n26 = spark.sql("select count(*) c from silver_plays where season=2026").first().c
assert n26 == spark.read.parquet(str(DATA / "play_by_play_2026.parquet")).count(), n26

# ---- gold
gold = "\n;\n".join((PROJ / f"src/pipelines/{f}").read_text() for f in ("nfl_gold.sql", "nfl_gold_gm.sql"))
gold = "\n".join(l for l in gold.splitlines() if not l.strip().startswith("--"))
for stmt in [s.strip() for s in gold.split(";") if s.strip()]:
    m = re.match(r'CREATE OR REFRESH MATERIALIZED VIEW (\w+)\s+COMMENT "[^"]*"\s+AS\s+(.*)', stmt, re.S)
    assert m, stmt[:80]
    spark.sql(m.group(2)).localCheckpoint().createOrReplaceTempView(m.group(1))
    print(m.group(1), spark.table(m.group(1)).count())

spark.sql("""select season, team, wins, losses, ats_covers, round(off_epa_per_play,3) off, round(def_epa_per_play,3) def,
             round(net_epa_per_play,3) net, net_epa_rank from gold_team_season where season in (2025, 2026) and net_epa_rank <= 3
             order by season, net_epa_rank""").show(truncate=False)
spark.sql("""select season, player_name, latest_team, dropbacks, round(epa_per_dropback,3) epa_db, round(cpoe,2) cpoe, epa_rank
             from gold_qb_season where season = 2026 and epa_rank <= 5 order by epa_rank""").show(truncate=False)
spark.sql("""select game_id, team, opponent, home_away, points_for, points_against, margin, expected_margin, cover_margin, ats_outcome,
             round(net_epa_per_play,3) net from gold_team_games where season = 2026 order by game_date desc, game_id limit 4""").show(truncate=False)
# sanity: each completed game appears exactly twice, margins mirror
bad = spark.sql("select game_id from gold_team_games group by game_id having count(*) != 2 or sum(margin) != 0").count()
assert bad == 0, bad
# relocated franchises: schedule codes (STL/SD/OAK) must line up with play-by-play codes (LA/LAC/LV)
orphans = spark.sql("""select season, team from gold_team_season
                       where season in (1999, 2010, 2020) and wins is null""").collect()
assert not orphans, f"team-seasons with plays but no record (team-code mismatch): {orphans}"
assert spark.sql("select count(*) c from silver_games where home_team in ('STL','SD','OAK') or away_team in ('STL','SD','OAK')").first().c == 0
# luck_gap is governed in gold: LA 2026 is 4-4 (#15 record) but #4 in net EPA -> -11 (unlucky)
la = spark.sql("select net_epa_rank, record_rank, luck_gap from gold_team_season where season = 2026 and team = 'LA'").first()
assert (la.net_epa_rank, la.record_rank, la.luck_gap) == (4, 15, -11), la
# ---- standings: the Giants answer that went wrong. NYG lead the NFC East at 4-2-1 -> a top-4 seed.
st = {r.team: r for r in spark.sql("select * from gold_standings where season = 2026").collect()}
assert st["NYG"].conference == "NFC" and st["NYG"].division == "NFC East", st["NYG"]
assert st["NYG"].division_leader and st["NYG"].conference_seed <= 4, st["NYG"]
assert st["CAR"].division_leader, st["CAR"]                      # 3-4 still leads the NFC South
for conf in ("AFC", "NFC"):
    seeds = sorted(r.conference_seed for r in st.values() if r.conference == conf)
    assert seeds == list(range(1, 17)), (conf, seeds)              # 16 teams, seeds 1..16, no gaps
    assert sum(r.division_leader for r in st.values() if r.conference == conf) == 4
assert spark.sql("select count(*) c from gold_standings where season < 2002").first().c == 0

# ---- betting: both teams in a game share one O/U result; ATS splits add up
bad_ou = spark.sql("select game_id from gold_team_games where ou_outcome is not null group by game_id having count(distinct ou_outcome) != 1").count()
assert bad_ou == 0, bad_ou
b = spark.sql("""select b.*, s.ats_covers s_cov from gold_team_betting b join gold_team_season s using (season, team)""").collect()
assert all(r.ats_covers == r.s_cov for r in b)
assert all(r.favorite_covers + r.underdog_covers <= r.ats_covers for r in b)
assert all(r.overs + r.unders + r.ou_pushes <= r.games for r in b)

# ---- players: full names (not "Jared"), headshots
dart = spark.sql("select * from gold_player_season where season = 2026 and player_name = 'Jaxson Dart'").collect()
assert dart and dart[0].position == "QB" and dart[0].headshot_url.startswith("https://"), dart
winston = spark.sql("select player_name, headshot_url from gold_qb_season where season = 2026 and player_short_name = 'J.Winston'").first()
assert winston.player_name == "Jameis Winston" and winston.headshot_url, winston
assert spark.sql("select count(*) c from gold_player_season where season = 1999").first().c > 1000
# ---- value model v2 + availability: the two cases Ben flagged
burns = spark.sql("select * from gold_player_value where player_name = 'Brian Burns'").first()
assert burns.games_played == 3 and burns.games_missed_injured >= 4, (burns.games_played, burns.games_missed_injured)
assert burns.current_roster_status == "injured reserve", burns.current_roster_status
assert burns.production_basis.startswith("last season (2025)"), burns.production_basis   # not judged on 3 games
likely = spark.sql("select * from gold_player_value where player_name = 'Isaiah Likely'").first()
assert likely.performance_tier in ("elite", "very good"), (likely.performance_tier, likely.production_pct)
assert likely.production_metric_name == "Receiving EPA per game", likely.production_metric_name
assert spark.sql("select count(*) c from gold_player_value where position_group = 'OL' and value_score is not null").first().c == 0
ir = spark.sql("select status from gold_injury_report where player_name = 'Brian Burns'").first()
assert ir is not None and ir.status == "injured reserve", ir                                   # IR players are listed
print("ALL CHECKS PASSED")
