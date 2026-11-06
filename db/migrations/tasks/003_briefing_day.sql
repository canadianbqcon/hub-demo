-- Per-day briefing snapshot: freezes the little bits of a day's briefing that are
-- derived from live state (the weather forecast and the weather/situation-derived
-- bring + prep items) so that looking back at a past day shows what was true then,
-- not "no forecast" / an empty bring list. Event-authored bring already persists
-- via the calendar event's description; this table captures the parts that would
-- otherwise vanish on rollover.
--
-- Write rule (enforced in app code, not SQL): only the server's current local day
-- is ever written/updated. Once a day is in the past its row is frozen — never
-- overwritten — so the snapshot is a durable record. The store keeps every day
-- forever; nothing expires.
--
-- bring/prep are JSON arrays of strings (the merged, deduped lists as shown that
-- day). forecast columns mirror the client weather entry {temp,code,hi,lo,precip}
-- in °F / WMO codes. See wiki/decisions (briefing snapshot) + chrome.jsx useNycWeather.

-- +migrate up
CREATE TABLE briefing_day (
    date       TEXT    NOT NULL PRIMARY KEY,   -- local YYYY-MM-DD
    temp       INTEGER,                        -- headline temp (°F); today = live current
    code       INTEGER,                        -- WMO weather code
    hi         INTEGER,                        -- daily high (°F)
    lo         INTEGER,                        -- daily low (°F)
    precip     INTEGER,                        -- daily max precip probability (%)
    bring      TEXT    NOT NULL DEFAULT '[]',  -- JSON array of bring labels
    prep       TEXT    NOT NULL DEFAULT '[]',  -- JSON array of prep labels
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
) STRICT;

-- +migrate down
DROP TABLE briefing_day;
