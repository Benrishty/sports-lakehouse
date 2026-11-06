-- Datasets for the "GM Office" dashboard. Each block starting with an at-sign marker is one dataset.
-- Team-scoped datasets expose a `team` column, which the dashboard-wide Team filter binds to.
-- League-wide datasets call the team `club` on purpose, so the Team filter leaves them unfiltered.
-- Everything is the current season unless the dataset says otherwise.

-- @gm_summary
SELECT st.team, st.team_name, s.team_logo_url,
       CONCAT(st.wins, '-', st.losses, IF(st.ties > 0, CONCAT('-', st.ties), '')) AS record,
       st.division, st.division_rank, st.division_games_back, st.conference_seed, st.in_playoff_position,
       s.net_epa_rank, s.luck_gap, ROUND(s.net_epa_per_play, 3) AS net_epa_per_play,
       CONCAT(b.ats_covers, '-', b.ats_losses) AS ats_record
FROM workspace.nfl.gold_standings st
JOIN workspace.nfl.gold_team_season s ON s.season = st.season AND s.team = st.team
LEFT JOIN workspace.nfl.gold_team_betting b ON b.season = st.season AND b.team = st.team
WHERE st.season = (SELECT MAX(season) FROM workspace.nfl.gold_standings);

-- @gm_report_card
SELECT r.team, r.metric_order, r.phase, r.metric,
       CASE WHEN r.metric LIKE '%rate%' OR r.metric LIKE '%percentage%'
              THEN CONCAT(FORMAT_NUMBER(100 * r.value, 1), '%')
            WHEN r.metric LIKE '%EPA%' THEN FORMAT_NUMBER(r.value, 3)
            ELSE FORMAT_NUMBER(r.value, 1) END AS value,
       CASE WHEN r.metric LIKE '%rate%' OR r.metric LIKE '%percentage%'
              THEN CONCAT(FORMAT_NUMBER(100 * r.league_avg, 1), '%')
            WHEN r.metric LIKE '%EPA%' THEN FORMAT_NUMBER(r.league_avg, 3)
            ELSE FORMAT_NUMBER(r.league_avg, 1) END AS league_avg,
       r.league_rank,
       CASE r.tier WHEN 'top tier' THEN '🟢 top tier' WHEN 'above average' THEN '🟡 above average'
                   WHEN 'below average' THEN '🟠 below average' WHEN 'bottom tier' THEN '🔴 bottom tier'
                   ELSE '⚪ tendency' END AS tier,
       ROUND(100 * r.percentile) AS percentile
FROM workspace.nfl.gold_team_report_card r
WHERE r.season = (SELECT MAX(season) FROM workspace.nfl.gold_team_report_card)
ORDER BY r.metric_order;

-- @gm_percentiles
SELECT r.team, CONCAT(r.phase, ': ', r.metric) AS metric, ROUND(100 * r.percentile) AS percentile
FROM workspace.nfl.gold_team_report_card r
WHERE r.season = (SELECT MAX(season) FROM workspace.nfl.gold_team_report_card) AND r.better <> 'neutral';

-- @gm_freshness
SELECT source, latest_season, latest_week, cadence FROM workspace.nfl.gold_data_freshness;

-- @gm_cap_allocation
SELECT c.team, c.position_group, c.players, ROUND(c.apy_m, 1) AS apy_m,
       ROUND(100 * c.share_of_team_apy, 1) AS team_share_pct,
       ROUND(100 * c.league_avg_share, 1) AS league_avg_pct,
       ROUND(100 * c.top8_avg_share, 1) AS top8_avg_pct,
       ROUND(100 * c.share_vs_league, 1) AS vs_league_pts
FROM workspace.nfl.gold_cap_allocation c
ORDER BY c.share_of_team_apy DESC;

-- @gm_roster_value
SELECT v.team, v.headshot_url, v.player_name, v.position_group, v.age,
       ROUND(v.apy_m, 1) AS apy_m, ROUND(v.guaranteed_m, 1) AS guaranteed_m, v.final_season,
       v.role, ROUND(100 * v.snap_share) AS snap_pct, v.production_metric_name,
       ROUND(v.production_metric, 2) AS production, ROUND(100 * v.value_score) AS value_score,
       CASE WHEN v.value_score >= 0.25 THEN '💰 bargain' WHEN v.value_score <= -0.25 THEN '⚠️ overpaid'
            WHEN v.value_score IS NULL THEN '' ELSE 'fair' END AS verdict
FROM workspace.nfl.gold_player_value v
WHERE v.team IS NOT NULL
ORDER BY v.apy_m DESC;

-- @gm_expiring
SELECT v.team, v.headshot_url, v.player_name, v.position_group, v.age, ROUND(v.apy_m, 1) AS apy_m,
       v.final_season, v.role, ROUND(100 * v.snap_share) AS snap_pct, ROUND(100 * v.value_score) AS value_score
FROM workspace.nfl.gold_player_value v
WHERE v.team IS NOT NULL AND v.final_season <= v.season
ORDER BY v.snap_share DESC NULLS LAST, v.apy_m DESC;

-- @gm_personnel
SELECT a.latest_team AS team, a.headshot_url, a.player_name, a.position_group, a.role,
       ROUND(100 * a.snap_share) AS snap_pct, a.games,
       ROUND(COALESCE(a.passing_epa, 0) + COALESCE(a.rushing_epa, 0) + COALESCE(a.receiving_epa, 0), 1) AS offensive_epa,
       ROUND(a.rush_yards_over_expected_per_att, 2) AS ryoe_per_att,
       ROUND(a.avg_separation, 2) AS separation_yds,
       ROUND(a.avg_yac_above_expectation, 2) AS yac_over_expected,
       a.sacks_plus_hits,
       ROUND(a.sacks_hits_per_100_snaps, 1) AS sacks_hits_per_100,
       ROUND(a.ball_production_per_100_snaps, 1) AS pd_int_per_100,
       ROUND(a.tackles_per_100_snaps, 1) AS tackles_per_100
FROM workspace.nfl.gold_player_advanced a
WHERE a.season = (SELECT MAX(season) FROM workspace.nfl.gold_player_advanced) AND a.snap_share >= 0.25
ORDER BY CASE a.position_group WHEN 'QB' THEN 1 WHEN 'RB' THEN 2 WHEN 'WR' THEN 3 WHEN 'TE' THEN 4 WHEN 'OL' THEN 5
                               WHEN 'DL' THEN 6 WHEN 'LB' THEN 7 WHEN 'DB' THEN 8 ELSE 9 END, a.snap_share DESC;

-- @gm_draft_projection
SELECT p.projected_pick, t.team_logo_url, p.team AS club, p.team_name,
       CONCAT(p.wins, '-', p.losses, IF(p.ties > 0, CONCAT('-', p.ties), '')) AS record,
       ROUND(p.point_differential) AS point_diff, IF(p.in_playoff_position, 'playoff spot', '') AS status
FROM workspace.nfl.gold_draft_order_projection p
LEFT JOIN workspace.nfl.silver_teams t ON t.team = p.team
ORDER BY p.projected_pick;

-- @gm_draft_classes
SELECT g.team, g.draft_year, g.picks, g.hits, g.pro_bowlers, ROUND(g.surplus_av, 1) AS surplus_av, g.class_rank
FROM workspace.nfl.gold_draft_team_grades g
ORDER BY g.draft_year;

-- @gm_draft_best_misses
SELECT team, kind, headshot_url, draft_year, round, pick, player_name, position, dr_av, expected_av, surplus_av, seasons_started, probowls
FROM (
  SELECT d.team, d.headshot_url, d.draft_year, d.round, d.pick, d.player_name, d.position, d.dr_av,
         ROUND(d.expected_dr_av, 1) AS expected_av, ROUND(d.surplus_av, 1) AS surplus_av, d.seasons_started, d.probowls,
         ROW_NUMBER() OVER (PARTITION BY d.team ORDER BY d.surplus_av DESC) AS best_rk,
         ROW_NUMBER() OVER (PARTITION BY d.team ORDER BY d.surplus_av ASC) AS miss_rk,
         IF(ROW_NUMBER() OVER (PARTITION BY d.team ORDER BY d.surplus_av DESC) <= 10, '✅ best value', '❌ biggest miss') AS kind
  FROM workspace.nfl.gold_draft_pick_value d
  WHERE d.is_mature AND d.draft_year >= (SELECT MAX(draft_year) - 15 FROM workspace.nfl.gold_draft_pick_value) AND d.round <= 3
)
WHERE best_rk <= 10 OR miss_rk <= 10
ORDER BY kind DESC, surplus_av DESC;

-- @gm_position_value
SELECT round, position, picks, ROUND(100 * hit_rate) AS hit_rate_pct, ROUND(100 * pro_bowl_rate) AS pro_bowl_pct,
       ROUND(avg_av_for_team, 1) AS avg_av
FROM workspace.nfl.gold_draft_position_value
WHERE round <= 3 AND picks >= 15
ORDER BY round, hit_rate DESC;

-- @gm_injuries
SELECT i.team, i.headshot_url, i.player_name, i.position, COALESCE(i.report_status, 'Limited/none') AS status, i.injury,
       i.practice_status, i.role, ROUND(100 * i.snap_share) AS snap_pct, ROUND(i.apy_m, 1) AS apy_m, i.week
FROM workspace.nfl.gold_injury_report i
ORDER BY CASE i.report_status WHEN 'Out' THEN 1 WHEN 'Doubtful' THEN 2 WHEN 'Questionable' THEN 3 ELSE 4 END,
         i.snap_share DESC NULLS LAST;

-- @gm_injury_league
SELECT x.team AS club, x.starter_games_out, x.starters_missing_time, x.player_games_out,
       ROUND(x.starter_apy_affected_m, 1) AS starter_apy_affected_m, x.rank_fewest_starter_games_lost
FROM workspace.nfl.gold_team_injury_impact x
WHERE x.season = (SELECT MAX(season) FROM workspace.nfl.gold_team_injury_impact)
ORDER BY x.starter_games_out DESC;
