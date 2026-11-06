-- The full day of weather behind a briefing snapshot, so a past day shows that
-- day's own weather (hourly row, wind, uv, sun, humidity), not the week ahead
-- (2026-11-03 mark: "for past days, this should show only that days weather,
-- and store them in vault for 1 month").
--
-- JSON object {feels, wind, uv, sunrise, sunset, hum, hours: [{iso, hour, temp,
-- code, precip, hum}]}. Kept 31 days: briefing_snapshot.save_today clears it on
-- older rows. The five base forecast columns stay forever as before.

-- +migrate up
ALTER TABLE briefing_day ADD COLUMN wx TEXT;

-- +migrate down
ALTER TABLE briefing_day DROP COLUMN wx;
