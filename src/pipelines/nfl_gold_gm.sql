-- GM marts: the front-office layer on top of the core gold tables.
-- Questions they answer: where is my team weak (report card), who is worth their contract (player value),
-- how is my cap spread (cap allocation), how well do we draft (draft value, grades, projected order),
-- what is the injury picture (injury report, starter games lost), and how do players grade on tracking and
-- charting data (player advanced).
-- Conventions: regular season only unless stated; team = franchise code; snap shares are 0-1.

-- ---------------------------------------------------------------- team phase stats (team × season × side)
CREATE OR REFRESH MATERIALIZED VIEW gold_team_phase_stats
COMMENT "One row per team per regular season per side (offense = plays run, defense = plays faced): EPA by pass/rush, success, explosives, sack and pressure (hits + sacks) rate, 3rd down, red zone TD rate, turnovers, early-down pass rate over expected, and from 2022 FTN play-action and blitz rates."
AS
WITH p AS (
  SELECT p.*, f.is_play_action, f.n_blitzers
  FROM silver_plays p
  LEFT JOIN silver_ftn_charting f ON f.game_id = p.game_id AND f.play_id = p.play_id
  WHERE p.season_type = 'REG' AND p.posteam IS NOT NULL
),
scrim AS (SELECT * FROM p WHERE (is_pass = 1 OR is_rush = 1) AND epa IS NOT NULL),
sided AS (
  SELECT season, posteam AS team, 'offense' AS side, epa, qb_dropback, is_pass, is_rush, success, yards_gained, sack, qb_hit, third_down_converted, third_down_failed, interception, fumble_lost, down, pass_oe, is_play_action, n_blitzers FROM scrim
  UNION ALL
  SELECT season, defteam AS team, 'defense' AS side, epa, qb_dropback, is_pass, is_rush, success, yards_gained, sack, qb_hit, third_down_converted, third_down_failed, interception, fumble_lost, down, pass_oe, is_play_action, n_blitzers FROM scrim
),
plays AS (
  SELECT season, team, side,
    COUNT(*) AS plays,
    AVG(epa) AS epa_per_play,
    AVG(CASE WHEN qb_dropback = 1 THEN epa END) AS pass_epa_per_dropback,
    AVG(CASE WHEN is_rush = 1 AND qb_dropback = 0 THEN epa END) AS rush_epa_per_play,
    AVG(success) AS success_rate,
    AVG(CASE WHEN (is_pass = 1 AND yards_gained >= 20) OR (is_rush = 1 AND yards_gained >= 10) THEN 1 ELSE 0 END) AS explosive_rate,
    SUM(sack) / NULLIF(SUM(qb_dropback), 0) AS sack_rate,
    SUM(CASE WHEN qb_hit = 1 OR sack = 1 THEN 1 ELSE 0 END) / NULLIF(SUM(qb_dropback), 0) AS pressure_rate,
    SUM(third_down_converted) / NULLIF(SUM(third_down_converted) + SUM(third_down_failed), 0) AS third_down_rate,
    100.0 * SUM(interception + fumble_lost) / COUNT(*) AS turnovers_per_100_plays,
    AVG(CASE WHEN down IN (1, 2) THEN pass_oe END) AS early_down_pass_oe,
    AVG(CASE WHEN qb_dropback = 1 THEN CAST(is_play_action AS INT) END) AS play_action_rate,
    AVG(CASE WHEN qb_dropback = 1 AND is_play_action THEN epa END) AS play_action_epa,
    AVG(CASE WHEN qb_dropback = 1 AND n_blitzers IS NOT NULL THEN IF(n_blitzers > 0, 1, 0) END) AS blitz_rate
  FROM sided
  GROUP BY season, team, side
),
drives AS (
  SELECT season, game_id, drive_id, ANY_VALUE(posteam) AS posteam, ANY_VALUE(defteam) AS defteam,
         MAX(IF(yardline_100 <= 20, 1, 0)) AS reached_red_zone, MAX(drive_result) AS drive_result
  FROM p WHERE drive_id IS NOT NULL
  GROUP BY season, game_id, drive_id
),
red_zone AS (
  SELECT season, team, side, COUNT(*) AS red_zone_trips,
         AVG(IF(drive_result = 'Touchdown', 1, 0)) AS red_zone_td_rate
  FROM (SELECT season, posteam AS team, 'offense' AS side, drive_result FROM drives WHERE reached_red_zone = 1
        UNION ALL
        SELECT season, defteam, 'defense', drive_result FROM drives WHERE reached_red_zone = 1)
  GROUP BY season, team, side
)
SELECT pl.*, rz.red_zone_trips, rz.red_zone_td_rate
FROM plays pl
LEFT JOIN red_zone rz ON rz.season = pl.season AND rz.team = pl.team AND rz.side = pl.side;

-- ---------------------------------------------------------------- team report card (long)
CREATE OR REFRESH MATERIALIZED VIEW gold_team_report_card
COMMENT "One row per team per regular season per metric: unit (Offense / Defense / Special teams / Discipline / Overall), phase, value, league rank (1 = best), percentile, league average and tier (1-8 top, 9-16 above average, 17-24 below average, 25-32 bottom). Direction-aware: for 'lower is better' metrics rank 1 is the lowest value. Neutral tendency metrics (pass rate over expected, play-action rate, blitz rate) are ranked high-to-low with tier 'tendency'."
AS
WITH o AS (SELECT * FROM gold_team_phase_stats WHERE side = 'offense'),
d AS (SELECT * FROM gold_team_phase_stats WHERE side = 'defense'),
kicking AS (
  SELECT season, posteam AS team,
         AVG(CASE WHEN field_goal_result = 'made' THEN 1.0 WHEN field_goal_result IN ('missed', 'blocked') THEN 0.0 END) AS fg_pct
  FROM silver_plays WHERE season_type = 'REG' AND field_goal_result IS NOT NULL
  GROUP BY season, posteam
),
penalties AS (
  SELECT pn.season, pn.penalty_team AS team, SUM(pn.penalty_yards) / MAX(s.games) AS penalty_yards_per_game
  FROM silver_plays pn
  JOIN gold_team_season s ON s.season = pn.season AND s.team = pn.penalty_team
  WHERE pn.season_type = 'REG' AND pn.penalty_team IS NOT NULL
  GROUP BY pn.season, pn.penalty_team
),
wide AS (
  SELECT o.season, o.team,
    o.epa_per_play AS o_epa, o.pass_epa_per_dropback AS o_pass, o.rush_epa_per_play AS o_rush, o.success_rate AS o_succ,
    o.explosive_rate AS o_expl, o.sack_rate AS o_sack, o.pressure_rate AS o_press, o.third_down_rate AS o_3rd,
    o.red_zone_td_rate AS o_rz, o.turnovers_per_100_plays AS o_to, o.early_down_pass_oe AS o_proe, o.play_action_rate AS o_pa,
    d.epa_per_play AS d_epa, d.pass_epa_per_dropback AS d_pass, d.rush_epa_per_play AS d_rush, d.success_rate AS d_succ,
    d.explosive_rate AS d_expl, d.sack_rate AS d_sack, d.pressure_rate AS d_press, d.third_down_rate AS d_3rd,
    d.red_zone_td_rate AS d_rz, d.turnovers_per_100_plays AS d_to, d.blitz_rate AS d_blitz,
    k.fg_pct, pen.penalty_yards_per_game
  FROM o
  JOIN d ON d.season = o.season AND d.team = o.team
  LEFT JOIN kicking k ON k.season = o.season AND k.team = o.team
  LEFT JOIN penalties pen ON pen.season = o.season AND pen.team = o.team
),
long AS (
  SELECT season, team,
    stack(26,
      1,  'Offense',          'EPA per play',                     CAST(o_epa AS DOUBLE),   'higher',
      2,  'Pass offense',     'EPA per dropback',                 CAST(o_pass AS DOUBLE),  'higher',
      3,  'Rush offense',     'EPA per designed run',             CAST(o_rush AS DOUBLE),  'higher',
      4,  'Offense',          'Success rate',                     CAST(o_succ AS DOUBLE),  'higher',
      5,  'Offense',          'Explosive play rate',              CAST(o_expl AS DOUBLE),  'higher',
      6,  'Pass protection',  'Sack rate allowed',                CAST(o_sack AS DOUBLE),  'lower',
      7,  'Pass protection',  'Pressure rate allowed (hits + sacks)', CAST(o_press AS DOUBLE), 'lower',
      8,  'Situational O',    '3rd down conversion rate',         CAST(o_3rd AS DOUBLE),   'higher',
      9,  'Situational O',    'Red zone TD rate',                 CAST(o_rz AS DOUBLE),    'higher',
      10, 'Ball security',    'Giveaways per 100 plays',          CAST(o_to AS DOUBLE),    'lower',
      11, 'Tendencies',       'Early-down pass rate over expected', CAST(o_proe AS DOUBLE), 'neutral',
      12, 'Tendencies',       'Play-action rate (2022+)',         CAST(o_pa AS DOUBLE),    'neutral',
      13, 'Defense',          'EPA per play allowed',             CAST(d_epa AS DOUBLE),   'lower',
      14, 'Pass defense',     'EPA per dropback allowed',         CAST(d_pass AS DOUBLE),  'lower',
      15, 'Rush defense',     'EPA per designed run allowed',     CAST(d_rush AS DOUBLE),  'lower',
      16, 'Defense',          'Success rate allowed',             CAST(d_succ AS DOUBLE),  'lower',
      17, 'Defense',          'Explosive play rate allowed',      CAST(d_expl AS DOUBLE),  'lower',
      18, 'Pass rush',        'Sack rate',                        CAST(d_sack AS DOUBLE),  'higher',
      19, 'Pass rush',        'Pressure rate (hits + sacks)',     CAST(d_press AS DOUBLE), 'higher',
      20, 'Situational D',    '3rd down conversion rate allowed', CAST(d_3rd AS DOUBLE),   'lower',
      21, 'Situational D',    'Red zone TD rate allowed',         CAST(d_rz AS DOUBLE),    'lower',
      22, 'Takeaways',        'Takeaways per 100 plays',          CAST(d_to AS DOUBLE),    'higher',
      23, 'Tendencies',       'Blitz rate (2022+)',               CAST(d_blitz AS DOUBLE), 'neutral',
      24, 'Special teams',    'Field goal percentage',            CAST(fg_pct AS DOUBLE),  'higher',
      25, 'Discipline',       'Penalty yards per game',           CAST(penalty_yards_per_game AS DOUBLE), 'lower',
      26, 'Offense',          'Net EPA per play (offense - defense)', CAST(o_epa - d_epa AS DOUBLE), 'higher'
    ) AS (metric_order, phase, metric, value, better)
  FROM wide
)
SELECT
  season, team,
  -- unit groups every phase: "how is our defense?" means all defensive phases, not just the 'Defense' rows
  CASE WHEN metric_order = 26 THEN 'Overall' WHEN metric_order <= 12 THEN 'Offense' WHEN metric_order <= 23 THEN 'Defense'
       WHEN metric_order = 24 THEN 'Special teams' ELSE 'Discipline' END AS unit,
  metric_order, phase, metric, value, better,
  RANK() OVER (PARTITION BY season, metric ORDER BY CASE WHEN better = 'lower' THEN value ELSE -value END) AS league_rank,
  COUNT(value) OVER (PARTITION BY season, metric) AS teams_ranked,
  1 - (RANK() OVER (PARTITION BY season, metric ORDER BY CASE WHEN better = 'lower' THEN value ELSE -value END) - 1)
      / NULLIF(COUNT(value) OVER (PARTITION BY season, metric) - 1, 0) AS percentile,
  AVG(value) OVER (PARTITION BY season, metric) AS league_avg,
  CASE WHEN value IS NULL THEN NULL
       WHEN better = 'neutral' THEN 'tendency'
       WHEN RANK() OVER (PARTITION BY season, metric ORDER BY CASE WHEN better = 'lower' THEN value ELSE -value END) <= 8 THEN 'top tier'
       WHEN RANK() OVER (PARTITION BY season, metric ORDER BY CASE WHEN better = 'lower' THEN value ELSE -value END) <= 16 THEN 'above average'
       WHEN RANK() OVER (PARTITION BY season, metric ORDER BY CASE WHEN better = 'lower' THEN value ELSE -value END) <= 24 THEN 'below average'
       ELSE 'bottom tier' END AS tier
FROM long
WHERE value IS NOT NULL;

-- ---------------------------------------------------------------- player snaps (player × season × team)
CREATE OR REFRESH MATERIALIZED VIEW gold_player_snaps_season
COMMENT "One row per player per regular season per team, 2013+: games, snaps and average snap share by phase, and a role (starter >= 60% of the team's snaps on his side of the ball in games played, rotation 25-60%, reserve < 25%). player_id is the gsis id via the PFR crosswalk."
AS
SELECT
  s.season, s.team, s.pfr_player_id, pl.player_id, COALESCE(pl.player_name, MAX(s.player_name)) AS player_name,
  MAX_BY(s.position, s.week) AS position, pl.headshot_url,
  COUNT(*) AS games,
  SUM(s.offense_snaps) AS offense_snaps, SUM(s.defense_snaps) AS defense_snaps, SUM(s.st_snaps) AS st_snaps,
  AVG(s.offense_pct) AS avg_offense_share, AVG(s.defense_pct) AS avg_defense_share, AVG(s.st_pct) AS avg_st_share,
  GREATEST(AVG(s.offense_pct), AVG(s.defense_pct)) AS avg_snap_share,
  CASE WHEN GREATEST(AVG(s.offense_pct), AVG(s.defense_pct)) >= 0.6 THEN 'starter'
       WHEN GREATEST(AVG(s.offense_pct), AVG(s.defense_pct)) >= 0.25 THEN 'rotation'
       ELSE 'reserve' END AS role
FROM silver_snap_counts s
LEFT JOIN silver_players pl ON pl.pfr_id = s.pfr_player_id
WHERE s.game_type = 'REG'
GROUP BY s.season, s.team, s.pfr_player_id, pl.player_id, pl.player_name, pl.headshot_url;

-- ---------------------------------------------------------------- defensive credit from play-by-play
CREATE OR REFRESH MATERIALIZED VIEW gold_player_defense_pbp
COMMENT "Defensive credit per player per regular season from play-by-play (complete and current every week, unlike PFR advanced which lags in-season): sacks (half sacks = 0.5), QB hits, passes defensed, interceptions."
AS
WITH credit AS (
  SELECT season, defteam AS team, sack_player_id AS player_id, 1.0 AS sacks, 0 AS qb_hits, 0 AS passes_defensed, 0 AS interceptions FROM silver_plays WHERE season_type = 'REG' AND sack_player_id IS NOT NULL
  UNION ALL SELECT season, defteam, half_sack_1_player_id, 0.5, 0, 0, 0 FROM silver_plays WHERE season_type = 'REG' AND half_sack_1_player_id IS NOT NULL
  UNION ALL SELECT season, defteam, half_sack_2_player_id, 0.5, 0, 0, 0 FROM silver_plays WHERE season_type = 'REG' AND half_sack_2_player_id IS NOT NULL
  UNION ALL SELECT season, defteam, qb_hit_1_player_id, 0, 1, 0, 0 FROM silver_plays WHERE season_type = 'REG' AND qb_hit_1_player_id IS NOT NULL
  UNION ALL SELECT season, defteam, qb_hit_2_player_id, 0, 1, 0, 0 FROM silver_plays WHERE season_type = 'REG' AND qb_hit_2_player_id IS NOT NULL
  UNION ALL SELECT season, defteam, pass_defense_1_player_id, 0, 0, 1, 0 FROM silver_plays WHERE season_type = 'REG' AND pass_defense_1_player_id IS NOT NULL
  UNION ALL SELECT season, defteam, pass_defense_2_player_id, 0, 0, 1, 0 FROM silver_plays WHERE season_type = 'REG' AND pass_defense_2_player_id IS NOT NULL
  UNION ALL SELECT season, defteam, interception_player_id, 0, 0, 0, 1 FROM silver_plays WHERE season_type = 'REG' AND interception_player_id IS NOT NULL
)
SELECT season, player_id, MAX_BY(team, team) AS team,
  SUM(sacks) AS sacks, SUM(qb_hits) AS qb_hits, SUM(sacks) + SUM(qb_hits) AS sacks_plus_hits,
  SUM(passes_defensed) AS passes_defensed, SUM(interceptions) AS interceptions
FROM credit
GROUP BY season, player_id;

-- ---------------------------------------------------------------- player advanced (player × season)
CREATE OR REFRESH MATERIALIZED VIEW gold_player_advanced
COMMENT "One row per player per regular season: box score and EPA (all seasons) plus snap share (2012+), Next Gen Stats (2016+: time to throw, aggressiveness (%), CPOE (pct points), rush yards over expected, stacked-box rate (0-1), separation, YAC over expected, air-yards share (0-1)) and PFR advanced (2018+: pressure rate faced, bad throws, yards after contact, broken tackles, drops, pressures generated, missed tackles, coverage allowed)."
AS
WITH snaps AS (
  SELECT season, player_id, SUM(games) AS snap_games, SUM(offense_snaps) AS offense_snaps, SUM(defense_snaps) AS defense_snaps,
         MAX(avg_snap_share) AS snap_share, MAX_BY(role, games) AS role
  FROM gold_player_snaps_season WHERE player_id IS NOT NULL GROUP BY season, player_id
),
ngs_pass AS (SELECT * FROM silver_ngs_passing WHERE week = 0 AND season_type = 'REG'),
ngs_rush AS (SELECT * FROM silver_ngs_rushing WHERE week = 0 AND season_type = 'REG'),
ngs_rec AS (SELECT * FROM silver_ngs_receiving WHERE week = 0 AND season_type = 'REG'),
-- PFR: multi-team players have a combined '2TM'/'3TM' row plus per-team rows; keep the combined row
pfr_def AS (SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY pfr_player_id, season ORDER BY IF(team LIKE '_TM', 0, 1), games DESC) rn FROM silver_pfr_defense) WHERE rn = 1),
pfr_pass AS (SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY pfr_player_id, season ORDER BY IF(team LIKE '_TM', 0, 1), pass_attempts DESC) rn FROM silver_pfr_passing) WHERE rn = 1),
pfr_rush AS (SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY pfr_player_id, season ORDER BY IF(team LIKE '_TM', 0, 1), attempts DESC) rn FROM silver_pfr_rushing) WHERE rn = 1),
pfr_rec AS (SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY pfr_player_id, season ORDER BY IF(team LIKE '_TM', 0, 1), targets DESC) rn FROM silver_pfr_receiving) WHERE rn = 1)
SELECT
  g.season, g.player_id, g.player_name, g.position, g.position_group, g.latest_team, g.headshot_url, g.games,
  sn.offense_snaps, sn.defense_snaps, sn.snap_share, sn.role,
  g.pass_attempts, g.passing_yards, g.passing_tds, g.interceptions, g.passing_epa,
  g.carries, g.rushing_yards, g.rushing_tds, g.rushing_epa,
  g.targets, g.receptions, g.receiving_yards, g.receiving_tds, g.receiving_epa,
  g.solo_tackles + g.assisted_tackles AS tackles, g.sacks, g.def_interceptions, g.fantasy_points_ppr,
  -- Next Gen Stats
  np.avg_time_to_throw, np.aggressiveness, np.completion_percentage_above_expectation AS ngs_cpoe, np.avg_intended_air_yards,
  nr.rush_yards_over_expected, nr.rush_yards_over_expected_per_att, nr.percent_attempts_gte_eight_defenders / 100 AS stacked_box_rate,
  nv.avg_separation, nv.avg_cushion, nv.avg_yac_above_expectation, nv.percent_share_of_intended_air_yards / 100 AS air_yards_share,
  -- PFR advanced
  pp.pressure_pct AS pressure_rate_faced, pp.bad_throw_pct, pp.on_tgt_pct, pp.pocket_time,
  pr.ybc_att AS yards_before_contact_per_att, pr.yac_att AS yards_after_contact_per_att, pr.broken_tackles AS rush_broken_tackles,
  pc.drops, pc.drop_pct, pc.adot, pc.broken_tackles AS rec_broken_tackles, pc.passer_rating_when_targeted,
  pd.pressures, pd.hurries, pd.qb_knockdowns, pd.missed_tackles, pd.missed_tackle_pct,
  pd.targets_allowed, pd.completion_pct_allowed, pd.yards_allowed, pd.tds_allowed, pd.passer_rating_allowed,
  pd.games AS pfr_games,
  -- play-by-play defensive credit (current every week) and per-100-snap rates
  dp.sacks_plus_hits, dp.qb_hits, dp.passes_defensed, dp.interceptions AS pbp_interceptions,
  100.0 * dp.sacks_plus_hits / NULLIF(sn.defense_snaps, 0) AS sacks_hits_per_100_snaps,
  100.0 * (COALESCE(dp.passes_defensed, 0) + COALESCE(dp.interceptions, 0)) / NULLIF(sn.defense_snaps, 0) AS ball_production_per_100_snaps,
  100.0 * (g.solo_tackles + g.assisted_tackles) / NULLIF(sn.defense_snaps, 0) AS tackles_per_100_snaps
FROM gold_player_season g
LEFT JOIN silver_players pl ON pl.player_id = g.player_id
LEFT JOIN snaps sn ON sn.season = g.season AND sn.player_id = g.player_id
LEFT JOIN ngs_pass np ON np.season = g.season AND np.player_id = g.player_id
LEFT JOIN ngs_rush nr ON nr.season = g.season AND nr.player_id = g.player_id
LEFT JOIN ngs_rec nv ON nv.season = g.season AND nv.player_id = g.player_id
LEFT JOIN pfr_pass pp ON pp.season = g.season AND pp.pfr_player_id = pl.pfr_id
LEFT JOIN pfr_rush pr ON pr.season = g.season AND pr.pfr_player_id = pl.pfr_id
LEFT JOIN pfr_rec pc ON pc.season = g.season AND pc.pfr_player_id = pl.pfr_id
LEFT JOIN pfr_def pd ON pd.season = g.season AND pd.pfr_player_id = pl.pfr_id
LEFT JOIN gold_player_defense_pbp dp ON dp.season = g.season AND dp.player_id = g.player_id;

-- ---------------------------------------------------------------- player value (active contracts × current season)
CREATE OR REFRESH MATERIALIZED VIEW gold_player_value
COMMENT "One row per player on an active contract: team, contract (APY $M, guarantees, final season, years left), age, current-season role and production, and a value score = production percentile minus cost percentile WITHIN the position group (players with >= 25% snap share). Positive = outperforming the contract (bargain), negative = overpaid relative to peers. Production metric by group (all from weekly-updated play-by-play and box scores): QB EPA/dropback, RB rushing+receiving EPA, WR/TE receiving EPA, EDGE/IDL sacks + QB hits per 100 defensive snaps, LB tackles per 100 snaps, CB/S passes defensed + interceptions per 100 snaps. OL and K/P/LS are not scored (no individual blocking data in the sources)."
AS
WITH cur AS (SELECT MAX(season) AS season FROM silver_plays),
c AS (
  SELECT c.*,
    CASE WHEN c.position = 'QB' THEN 'QB' WHEN c.position IN ('RB', 'FB') THEN 'RB' WHEN c.position = 'WR' THEN 'WR'
         WHEN c.position = 'TE' THEN 'TE' WHEN c.position IN ('LT', 'LG', 'C', 'RG', 'RT') THEN 'OL'
         WHEN c.position = 'IDL' THEN 'IDL' WHEN c.position = 'ED' THEN 'EDGE' WHEN c.position = 'LB' THEN 'LB'
         WHEN c.position = 'CB' THEN 'CB' WHEN c.position = 'S' THEN 'S' ELSE 'ST' END AS position_group
  FROM (
    -- a handful of players carry two active deals in the OTC data: keep the most recent signing
    SELECT *, ROW_NUMBER() OVER (PARTITION BY COALESCE(player_id, CONCAT(otc_id, player_name))
                                 ORDER BY year_signed DESC, apy_m DESC) AS rn
    FROM silver_contracts WHERE is_active
  ) c WHERE c.rn = 1
),
base AS (
  SELECT
    cur.season, c.player_id, COALESCE(pl.player_name, c.player_name) AS player_name, c.position, c.position_group,
    COALESCE(pl.latest_team, IF(c.team_raw LIKE '%/%', element_at(split(c.team_raw, '/'), -1), NULL)) AS team,
    pl.headshot_url, FLOOR(DATEDIFF(make_date(cur.season, 9, 1), pl.birth_date) / 365.25) AS age,
    c.apy_m, c.apy_cap_pct, c.guaranteed_m, c.total_value_m, c.year_signed, c.final_season,
    c.final_season - cur.season AS years_left_after_this_season,
    a.games, a.snap_share, a.role,
    a.passing_epa, a.rushing_epa, a.receiving_epa, a.sacks, a.sacks_plus_hits, a.tackles, a.passes_defensed,
    a.pbp_interceptions, q.epa_per_dropback,
    CASE c.position_group
      WHEN 'QB' THEN q.epa_per_dropback
      WHEN 'RB' THEN COALESCE(a.rushing_epa, 0) + COALESCE(a.receiving_epa, 0)
      WHEN 'WR' THEN a.receiving_epa
      WHEN 'TE' THEN a.receiving_epa
      WHEN 'EDGE' THEN a.sacks_hits_per_100_snaps
      WHEN 'IDL' THEN a.sacks_hits_per_100_snaps
      WHEN 'LB' THEN a.tackles_per_100_snaps
      WHEN 'CB' THEN a.ball_production_per_100_snaps
      WHEN 'S' THEN a.ball_production_per_100_snaps
    END AS production_metric
  FROM c CROSS JOIN cur
  LEFT JOIN silver_players pl ON pl.player_id = c.player_id
  LEFT JOIN gold_player_advanced a ON a.season = cur.season AND a.player_id = c.player_id
  LEFT JOIN gold_qb_season q ON q.season = cur.season AND q.player_id = c.player_id
),
scored AS (
  SELECT *,
    PERCENT_RANK() OVER (PARTITION BY position_group ORDER BY production_metric) AS production_pct,
    PERCENT_RANK() OVER (PARTITION BY position_group ORDER BY apy_m) AS cost_pct
  FROM base
  WHERE production_metric IS NOT NULL AND snap_share >= 0.25 AND position_group <> 'ST'
)
SELECT b.*,
  CASE b.position_group WHEN 'QB' THEN 'EPA per dropback' WHEN 'RB' THEN 'Rush + receiving EPA'
       WHEN 'WR' THEN 'Receiving EPA' WHEN 'TE' THEN 'Receiving EPA' WHEN 'OL' THEN 'Not scored: no individual blocking data'
       WHEN 'EDGE' THEN 'Sacks + QB hits per 100 snaps' WHEN 'IDL' THEN 'Sacks + QB hits per 100 snaps'
       WHEN 'LB' THEN 'Tackles per 100 snaps'
       WHEN 'CB' THEN 'Passes defensed + INT per 100 snaps' WHEN 'S' THEN 'Passes defensed + INT per 100 snaps' END AS production_metric_name,
  s.production_pct, s.cost_pct, s.production_pct - s.cost_pct AS value_score
FROM base b
LEFT JOIN scored s ON s.player_id = b.player_id;

-- ---------------------------------------------------------------- cap allocation (team × position group)
CREATE OR REFRESH MATERIALIZED VIEW gold_cap_allocation
COMMENT "Active-contract spending (APY, $M) by team and position group: the group's share of the team's total APY, the league-average share, and the average share among the 8 best teams by current net EPA. APY is average annual value, not the exact current-year cap hit."
AS
WITH v AS (SELECT team, position_group, apy_m, player_id FROM gold_player_value WHERE team IS NOT NULL),
team_total AS (SELECT team, SUM(apy_m) AS team_apy_m FROM v GROUP BY team),
grp AS (
  SELECT v.team, v.position_group, COUNT(*) AS players, SUM(v.apy_m) AS apy_m, SUM(v.apy_m) / t.team_apy_m AS share_of_team_apy
  FROM v JOIN team_total t ON t.team = v.team GROUP BY v.team, v.position_group, t.team_apy_m
),
top8 AS (
  SELECT team FROM gold_team_season
  WHERE season = (SELECT MAX(season) FROM gold_team_season) AND net_epa_rank <= 8
)
SELECT g.*, t.team_apy_m,
  AVG(g.share_of_team_apy) OVER (PARTITION BY g.position_group) AS league_avg_share,
  AVG(IF(t8.team IS NOT NULL, g.share_of_team_apy, NULL)) OVER (PARTITION BY g.position_group) AS top8_avg_share,
  g.share_of_team_apy - AVG(g.share_of_team_apy) OVER (PARTITION BY g.position_group) AS share_vs_league
FROM grp g
JOIN team_total t ON t.team = g.team
LEFT JOIN top8 t8 ON t8.team = g.team;

-- ---------------------------------------------------------------- draft pick value (pick level, 2000+)
CREATE OR REFRESH MATERIALIZED VIEW gold_draft_pick_value
COMMENT "Every draft pick since 2000 vs. the value expected at its slot. expected_dr_av = average AV-for-drafting-team of picks within 4 slots in MATURE classes (drafted 5+ seasons ago), surplus_av = dr_av - expected_dr_av, meaningful only when is_mature. hit = 3+ seasons as a starter."
AS
WITH cur AS (SELECT MAX(draft_year) AS last_class FROM silver_draft_picks),
mature AS (SELECT d.* FROM silver_draft_picks d CROSS JOIN cur WHERE d.draft_year <= cur.last_class - 5),
slots AS (SELECT DISTINCT pick FROM silver_draft_picks),
expected AS (
  SELECT s.pick, AVG(m.dr_av) AS expected_dr_av, AVG(IF(m.seasons_started >= 3, 1.0, 0.0)) AS expected_hit_rate
  FROM slots s JOIN mature m ON m.pick BETWEEN s.pick - 4 AND s.pick + 4
  GROUP BY s.pick
)
SELECT d.*, e.expected_dr_av, e.expected_hit_rate,
  d.draft_year <= cur.last_class - 5 AS is_mature,
  d.dr_av - e.expected_dr_av AS surplus_av,
  d.seasons_started >= 3 AS hit,
  pl.headshot_url
FROM silver_draft_picks d CROSS JOIN cur
LEFT JOIN expected e ON e.pick = d.pick
LEFT JOIN silver_players pl ON pl.player_id = d.player_id;

-- ---------------------------------------------------------------- team draft grades (team × class)
CREATE OR REFRESH MATERIALIZED VIEW gold_draft_team_grades
COMMENT "Draft results per team per class (mature classes only, 5+ seasons old): picks, hits, Pro Bowlers, AV earned for the team vs. expected for the slots used, surplus, and rank among all teams for that class."
AS
SELECT draft_year, team,
  COUNT(*) AS picks, SUM(IF(hit, 1, 0)) AS hits, SUM(IF(probowls > 0, 1, 0)) AS pro_bowlers,
  SUM(dr_av) AS av_for_team, SUM(expected_dr_av) AS expected_av, SUM(surplus_av) AS surplus_av,
  RANK() OVER (PARTITION BY draft_year ORDER BY SUM(surplus_av) DESC) AS class_rank
FROM gold_draft_pick_value
WHERE is_mature
GROUP BY draft_year, team;

-- ---------------------------------------------------------------- position value by round
CREATE OR REFRESH MATERIALIZED VIEW gold_draft_position_value
COMMENT "Which positions pay off by round (mature classes since 2000): picks, hit rate (3+ seasons as a starter), Pro Bowl rate and average AV for the drafting team, per position and round."
AS
SELECT round, position, COUNT(*) AS picks,
  AVG(IF(hit, 1.0, 0.0)) AS hit_rate, AVG(IF(probowls > 0, 1.0, 0.0)) AS pro_bowl_rate,
  AVG(dr_av) AS avg_av_for_team, AVG(surplus_av) AS avg_surplus_av
FROM gold_draft_pick_value
WHERE is_mature
GROUP BY round, position;

-- ---------------------------------------------------------------- projected draft order
CREATE OR REFRESH MATERIALIZED VIEW gold_draft_order_projection
COMMENT "Projected first-round order for next spring's draft if the season ended today: teams outside playoff position pick 1-18 by worst win percentage (then point differential), playoff-position teams pick 19-32 in the same order. Ignores playoff results, strength-of-schedule tiebreaks and traded picks."
AS
SELECT season + 1 AS draft_year, team, team_name, wins, losses, ties, win_pct, point_differential, in_playoff_position,
  ROW_NUMBER() OVER (ORDER BY IF(in_playoff_position, 1, 0), win_pct, point_differential, team) AS projected_pick
FROM gold_standings
WHERE season = (SELECT MAX(season) FROM gold_standings);

-- ---------------------------------------------------------------- injury report (latest week)
CREATE OR REFRESH MATERIALIZED VIEW gold_injury_report
COMMENT "The latest official injury report of the current season: player, team, game status (Out / Doubtful / Questionable / none), injury, practice status, plus the player's season role, snap share and contract APY so a GM can see what is actually missing."
AS
WITH latest AS (
  SELECT MAX(season) AS season FROM silver_injuries
),
wk AS (SELECT MAX(i.week) AS week FROM silver_injuries i JOIN latest l ON i.season = l.season WHERE i.season_type = 'REG')
SELECT i.season, i.week, i.team, i.player_id, COALESCE(pl.player_name, i.player_name) AS player_name, i.position,
  i.report_status, i.report_primary_injury AS injury, i.practice_status,
  pl.headshot_url, a.role, a.snap_share, a.games, v.apy_m
FROM silver_injuries i
JOIN latest l ON i.season = l.season
JOIN wk ON i.week = wk.week
LEFT JOIN silver_players pl ON pl.player_id = i.player_id
LEFT JOIN gold_player_advanced a ON a.season = i.season AND a.player_id = i.player_id
LEFT JOIN gold_player_value v ON v.player_id = i.player_id
WHERE i.season_type = 'REG';

-- ---------------------------------------------------------------- starter games lost (team × season)
CREATE OR REFRESH MATERIALIZED VIEW gold_team_injury_impact
COMMENT "Games missed through injury per team per regular season (2013+, when snap roles exist): weeks a player was listed Out on the official report, total and for players whose season role was 'starter' (>= 60% snap share when playing), with the contract APY of starters affected this season, and league rank (1 = fewest starter games lost)."
AS
WITH out_weeks AS (
  SELECT i.season, i.team, i.player_id, COUNT(DISTINCT i.week) AS weeks_out
  FROM silver_injuries i
  WHERE i.season_type = 'REG' AND i.report_status = 'Out' AND i.season >= 2013
  GROUP BY i.season, i.team, i.player_id
)
SELECT o.season, o.team,
  SUM(o.weeks_out) AS player_games_out,
  SUM(IF(a.role = 'starter', o.weeks_out, 0)) AS starter_games_out,
  COUNT(DISTINCT IF(a.role = 'starter', o.player_id, NULL)) AS starters_missing_time,
  SUM(IF(a.role = 'starter', v.apy_m, 0)) AS starter_apy_affected_m,
  RANK() OVER (PARTITION BY o.season ORDER BY SUM(IF(a.role = 'starter', o.weeks_out, 0))) AS rank_fewest_starter_games_lost
FROM out_weeks o
LEFT JOIN gold_player_advanced a ON a.season = o.season AND a.player_id = o.player_id
LEFT JOIN gold_player_value v ON v.player_id = o.player_id AND v.season = o.season
GROUP BY o.season, o.team;

-- ---------------------------------------------------------------- data freshness
CREATE OR REFRESH MATERIALIZED VIEW gold_data_freshness
COMMENT "How current each source is: latest season and week (or games played) available. PFR advanced stats are season files that can lag weeks behind during the season. Use this to state what an answer is 'as of'."
AS
SELECT 'Play-by-play (EPA, situational, defensive credit)' AS source, MAX(season) AS latest_season,
       MAX(IF(season = (SELECT MAX(season) FROM silver_plays), week, NULL)) AS latest_week, 'weekly' AS cadence FROM silver_plays
UNION ALL SELECT 'Player box scores', MAX(season), MAX(IF(season = (SELECT MAX(season) FROM silver_player_week), week, NULL)), 'weekly' FROM silver_player_week
UNION ALL SELECT 'Snap counts', MAX(season), MAX(IF(season = (SELECT MAX(season) FROM silver_snap_counts), week, NULL)), 'weekly' FROM silver_snap_counts
UNION ALL SELECT 'Injury reports', MAX(season), MAX(IF(season = (SELECT MAX(season) FROM silver_injuries), week, NULL)), 'weekly' FROM silver_injuries
UNION ALL SELECT 'FTN charting', MAX(season), MAX(IF(season = (SELECT MAX(season) FROM silver_ftn_charting), week, NULL)), 'weekly' FROM silver_ftn_charting
UNION ALL SELECT 'Next Gen Stats', MAX(season), MAX(IF(season = (SELECT MAX(season) FROM silver_ngs_receiving), week, NULL)), 'weekly' FROM silver_ngs_receiving
UNION ALL SELECT 'PFR advanced (games played in latest file)', MAX(season), MAX(IF(season = (SELECT MAX(season) FROM silver_pfr_defense), games, NULL)), 'season file, lags in-season' FROM silver_pfr_defense
UNION ALL SELECT 'Contracts (latest signing year)', MAX(year_signed), NULL, 'refreshed with OverTheCap' FROM silver_contracts
UNION ALL SELECT 'Draft picks (latest class)', MAX(draft_year), NULL, 'after each draft' FROM silver_draft_picks;
