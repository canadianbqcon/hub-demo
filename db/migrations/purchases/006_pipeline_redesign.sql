-- Migration 006_pipeline_redesign for purchases.db
-- Generated: 2026-07-10
--
-- Purpose:
--   Back the seven-stage pipeline redesign (spec:
--   docs/specs/2026-07-10-purchases-pipeline-redesign-design.md).
--   Adds the research/understanding layer the module never had: the function
--   map (dimensions), brand reputation rollups (brands), credibility-graded
--   claims (evidence), price-vs-spec rungs (price_steps), the hard-constraint
--   sheet (constraints) and per-candidate checks (candidate_constraints).
--   Adds compare-stage grading prose to candidates, per-section status JSON to
--   decisions, and a dimension link to criteria. Remaps the old stage
--   vocabulary (discovery/exploring -> need, processing -> candidates).
--
-- ⚠ PRE-MIGRATION BACKUP: the migrate helper takes it automatically.

-- +migrate up

CREATE TABLE dimensions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id   INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    explainer     TEXT NOT NULL DEFAULT '',
    range_text    TEXT NOT NULL DEFAULT '',
    tier_low      TEXT NOT NULL DEFAULT '',
    tier_typical  TEXT NOT NULL DEFAULT '',
    tier_high     TEXT NOT NULL DEFAULT '',
    fit_zone      TEXT NOT NULL DEFAULT '',
    fit_reasoning TEXT NOT NULL DEFAULT '',
    sort          INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE INDEX idx_dimensions_decision ON dimensions(decision_id);

CREATE TABLE brands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    sort        INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE INDEX idx_brands_decision ON brands(decision_id);

CREATE TABLE evidence (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id  INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL DEFAULT 'brand',   -- brand | dimension | candidate
    subject      TEXT NOT NULL DEFAULT '',
    candidate_id INTEGER REFERENCES candidates(id) ON DELETE CASCADE,
    claim        TEXT NOT NULL,
    source_type  TEXT NOT NULL DEFAULT '',
    source_url   TEXT NOT NULL DEFAULT '',
    longevity    TEXT NOT NULL DEFAULT '',        -- anecdote | short-term | long-term | dataset
    grade        TEXT NOT NULL DEFAULT '',        -- holds | weak | refuted
    grade_reason TEXT NOT NULL DEFAULT ''
) STRICT;
CREATE INDEX idx_evidence_decision ON evidence(decision_id);

CREATE TABLE price_steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id   INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    dimension_id  INTEGER REFERENCES dimensions(id) ON DELETE SET NULL,
    label         TEXT NOT NULL,
    spec_value    TEXT NOT NULL DEFAULT '',
    price         REAL NOT NULL,
    per_unit_note TEXT NOT NULL DEFAULT '',
    knee          INTEGER NOT NULL DEFAULT 0,     -- 1 = diminishing-returns point
    note          TEXT NOT NULL DEFAULT ''
) STRICT;
CREATE INDEX idx_price_steps_decision ON price_steps(decision_id);

CREATE TABLE constraints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    requirement TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'proposed', -- proposed | locked
    origin      TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT ''
) STRICT;
CREATE INDEX idx_constraints_decision ON constraints(decision_id);

CREATE TABLE candidate_constraints (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id  INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    constraint_id INTEGER NOT NULL REFERENCES constraints(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'unknown', -- pass | fail | unknown
    note          TEXT NOT NULL DEFAULT '',
    UNIQUE (candidate_id, constraint_id)
) STRICT;
CREATE INDEX idx_candidate_constraints_candidate ON candidate_constraints(candidate_id);

ALTER TABLE candidates ADD COLUMN assessment TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions  ADD COLUMN section_state TEXT NOT NULL DEFAULT '{}';
ALTER TABLE criteria   ADD COLUMN dimension_id INTEGER REFERENCES dimensions(id);

UPDATE decisions SET stage = 'need'       WHERE stage IN ('discovery', 'exploring');
UPDATE decisions SET stage = 'candidates' WHERE stage = 'processing';

-- +migrate down

ALTER TABLE criteria   DROP COLUMN dimension_id;
ALTER TABLE decisions  DROP COLUMN section_state;
ALTER TABLE candidates DROP COLUMN assessment;
DROP TABLE candidate_constraints;
DROP TABLE constraints;
DROP TABLE price_steps;
DROP TABLE evidence;
DROP TABLE brands;
DROP TABLE dimensions;
-- stage remap is not reversed: need/candidates are a superset vocabulary.
