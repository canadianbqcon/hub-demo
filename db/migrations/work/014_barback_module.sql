-- +migrate up
-- Barback shift-companion module: duty/stock templates, snapshot runs, raw goods.
-- Template -> run snapshot model: starting a run copies template items into
-- checklist_run_item, so editing a template or re-seeding never mutates an
-- in-flight run. "incomplete" is NOT stored: it is derived at read time as
-- (status='archived' AND any child run_item.state still 'open').

CREATE TABLE checklist_template (
    id         INTEGER PRIMARY KEY,
    key        TEXT NOT NULL UNIQUE,   -- 'opening_barback' | 'closing_barback' | 'stock_check'
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,          -- 'duty' (binary) | 'stock' (three-state)
    sort_order INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE checklist_template_item (
    id          INTEGER PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES checklist_template(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    section     TEXT NOT NULL DEFAULT '',
    deadline    TEXT NOT NULL DEFAULT '',
    priority    TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE checklist_run (
    id           INTEGER PRIMARY KEY,
    template_id  INTEGER NOT NULL REFERENCES checklist_template(id),
    bar_date     TEXT NOT NULL,         -- ISO date of the bar-day
    started_at   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'archived'
    completed_at TEXT
) STRICT;

CREATE TABLE checklist_run_item (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES checklist_run(id) ON DELETE CASCADE,
    text_snapshot   TEXT NOT NULL,
    detail_snapshot TEXT NOT NULL DEFAULT '',
    section         TEXT NOT NULL DEFAULT '',
    deadline        TEXT NOT NULL DEFAULT '',
    priority        TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'open',  -- duty: 'open'|'done'; stock: 'open'|'good'|'low'|'out'
    state_at        TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE stock_raw_item (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,           -- 'Fresh juice'|'Produce'|'Dry garnish'|'Bottled & canned'
    sort_order INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX idx_run_active ON checklist_run(status, bar_date);
CREATE INDEX idx_run_item_run ON checklist_run_item(run_id);
CREATE INDEX idx_template_item_tpl ON checklist_template_item(template_id);

-- +migrate down
DROP INDEX IF EXISTS idx_template_item_tpl;
DROP INDEX IF EXISTS idx_run_item_run;
DROP INDEX IF EXISTS idx_run_active;
DROP TABLE IF EXISTS stock_raw_item;
DROP TABLE IF EXISTS checklist_run_item;
DROP TABLE IF EXISTS checklist_run;
DROP TABLE IF EXISTS checklist_template_item;
DROP TABLE IF EXISTS checklist_template;
