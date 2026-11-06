-- NFL gold layer: business-ready materialized views over silver.
-- Grain is in each view's name. "Scrimmage play" = a pass or a rush with a valid EPA.
-- EPA (expected points added) comes from nflverse's model; success = EPA > 0.

-- ---------------------------------------------------------------- team × game
CREATE OR REFRESH MATERIALIZED VIEW gold_team_games
COMMENT "One row per team per completed game: score, margin vs. the closing spread, and EPA efficiency."
AS
WITH team_games AS (
  SELECT game_id, season, game_type, week, game_date,
         home_team AS team, away_team AS opponent, 'home' AS home_away,
         home_score AS points_for, away_score AS points_against,
         result AS margin, spread_line AS expected_margin, total_line
  FROM silver_games WHERE result IS NOT NULL
  UNION ALL
  SELECT game_id, season, game_type, week, game_date,
         away_team, home_team, 'away',
         away_score, home_score,
         -result, -spread_line, total_line
  FROM silver_games WHERE result IS NOT NULL
),
scrimmage AS (
  SELECT game_id, posteam, defteam, epa, success
  FROM silver_plays
  WHERE (is_pass = 1 OR is_rush = 1) AND epa IS NOT NULL AND posteam IS NOT NULL
),
off AS (
  SELECT game_id, posteam AS team, COUNT(*) AS off_plays, AVG(epa) AS off_epa_per_play, AVG(success) AS off_success_rate
  FROM scrimmage GROUP BY game_id, posteam
),
def AS (
  SELECT game_id, defteam AS team, COUNT(*) AS def_plays, AVG(epa) AS def_epa_per_play, AVG(success) AS def_success_rate
  FROM scrimmage GROUP BY game_id, defteam
)
SELECT
  g.*,
  CASE WHEN g.margin > 0 THEN 'W' WHEN g.margin < 0 THEN 'L' ELSE 'T' END AS outcome,
  g.margin - g.expected_margin AS cover_margin,
  CASE WHEN g.expected_margin IS NULL THEN NULL
       WHEN g.margin - g.expected_margin > 0 THEN 'cover'
       WHEN g.margin - g.expected_margin < 0 THEN 'no cover'
       ELSE 'push' END AS ats_outcome,
  o.off_plays, o.off_epa_per_play, o.off_success_rate,
  d.def_plays, d.def_epa_per_play, d.def_success_rate,
  o.off_epa_per_play - d.def_epa_per_play AS net_epa_per_play
FROM team_games g
LEFT JOIN off o ON o.game_id = g.game_id AND o.team = g.team
LEFT JOIN def d ON d.game_id = g.game_id AND d.team = g.team;

-- ---------------------------------------------------------------- team × season
CREATE OR REFRESH MATERIALIZED VIEW gold_team_season
COMMENT "One row per team per regular season: record, record against the spread, play-weighted EPA efficiency, league ranks and luck_gap (negative = unlucky, positive = lucky)."
AS
WITH scrimmage AS (
  SELECT season, posteam, defteam, epa, success, is_pass
  FROM silver_plays
  WHERE season_type = 'REG' AND (is_pass = 1 OR is_rush = 1) AND epa IS NOT NULL AND posteam IS NOT NULL
),
off AS (
  SELECT season, posteam AS team, COUNT(*) AS off_plays, AVG(epa) AS off_epa_per_play,
         AVG(success) AS off_success_rate, AVG(is_pass) AS pass_rate,
         AVG(CASE WHEN is_pass = 1 THEN epa END) AS off_pass_epa_per_play,
         AVG(CASE WHEN is_pass = 0 THEN epa END) AS off_rush_epa_per_play
  FROM scrimmage GROUP BY season, posteam
),
def AS (
  SELECT season, defteam AS team, COUNT(*) AS def_plays, AVG(epa) AS def_epa_per_play, AVG(success) AS def_success_rate
  FROM scrimmage GROUP BY season, defteam
),
record AS (
  SELECT season, team,
         COUNT(*) AS games,
         COUNT_IF(outcome = 'W') AS wins, COUNT_IF(outcome = 'L') AS losses, COUNT_IF(outcome = 'T') AS ties,
         COUNT_IF(ats_outcome = 'cover') AS ats_covers, COUNT_IF(ats_outcome = 'no cover') AS ats_losses,
         SUM(points_for) - SUM(points_against) AS point_differential,
         AVG(cover_margin) AS avg_cover_margin
  FROM gold_team_games WHERE game_type = 'REG'
  GROUP BY season, team
)
SELECT
  o.season, o.team,
  r.games, r.wins, r.losses, r.ties, r.ats_covers, r.ats_losses, r.point_differential, r.avg_cover_margin,
  o.off_plays, o.off_epa_per_play, o.off_success_rate, o.pass_rate, o.off_pass_epa_per_play, o.off_rush_epa_per_play,
  d.def_plays, d.def_epa_per_play, d.def_success_rate,
  o.off_epa_per_play - d.def_epa_per_play AS net_epa_per_play,
  RANK() OVER (PARTITION BY o.season ORDER BY o.off_epa_per_play DESC) AS off_epa_rank,
  RANK() OVER (PARTITION BY o.season ORDER BY d.def_epa_per_play ASC) AS def_epa_rank,
  RANK() OVER (PARTITION BY o.season ORDER BY o.off_epa_per_play - d.def_epa_per_play DESC) AS net_epa_rank,
  -- record rank by win percentage (ties count half), 1 = best record
  RANK() OVER (PARTITION BY o.season ORDER BY (r.wins + 0.5 * r.ties) / r.games DESC) AS record_rank,
  -- luck_gap = net_epa_rank - record_rank. Negative = UNLUCKY (plays better than its record);
  -- positive = LUCKY (record better than its play). Stored here so nobody re-derives the sign.
  RANK() OVER (PARTITION BY o.season ORDER BY o.off_epa_per_play - d.def_epa_per_play DESC)
    - RANK() OVER (PARTITION BY o.season ORDER BY (r.wins + 0.5 * r.ties) / r.games DESC) AS luck_gap
FROM off o
JOIN def d ON d.season = o.season AND d.team = o.team
LEFT JOIN record r ON r.season = o.season AND r.team = o.team;

-- ---------------------------------------------------------------- QB × season
CREATE OR REFRESH MATERIALIZED VIEW gold_qb_season
COMMENT "One row per quarterback per regular season (min. 100 dropbacks): EPA per dropback, CPOE, success rate."
AS
SELECT
  season,
  dropback_player_id AS player_id,
  MAX_BY(dropback_player_name, game_date) AS player_name,
  MAX_BY(posteam, game_date) AS latest_team,
  COUNT(DISTINCT game_id) AS games,
  COUNT(*) AS dropbacks,
  AVG(qb_epa) AS epa_per_dropback,
  SUM(qb_epa) AS total_epa,
  AVG(cpoe) AS cpoe,
  AVG(success) AS success_rate,
  SUM(sack) AS sacks,
  SUM(interception) AS interceptions,
  RANK() OVER (PARTITION BY season ORDER BY AVG(qb_epa) DESC) AS epa_rank
FROM silver_plays
WHERE season_type = 'REG' AND qb_dropback = 1 AND qb_epa IS NOT NULL AND dropback_player_id IS NOT NULL
GROUP BY season, dropback_player_id
HAVING COUNT(*) >= 100;
