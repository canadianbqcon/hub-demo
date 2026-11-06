-- Migration 004_candidate_scores for purchases.db
-- Generated: 2026-06-22
--
-- Purpose:
--   Add weighted per-criterion scoring so candidates can be ranked the way the
--   jobs module ranks applications by blended score. Until now `criteria.weight`
--   was stored but never applied to candidates — there was no candidate×criterion
--   score, so the compare surface could only show a static specs matrix.
--
--   candidate_scores holds one row per (candidate, criterion) the user has rated.
--   A missing row = "not yet scored" (rendered as a gap in the compare grid).
--   The weighted score per candidate is computed in db.get_full_decision():
--       sum(score * weight) / sum(weight)  over the criteria that candidate has
--   scored, alongside a coverage count (scored / total criteria) so a thinly
--   scored candidate is never silently ranked #1.
--
--   New table → STRICT per the warehouse contract. UNIQUE(candidate_id,
--   criterion_id) backs the upsert (one score per cell). Both FKs CASCADE so
--   deleting a candidate or a criterion drops its scores.
--
-- ⚠ PRE-MIGRATION BACKUP: the migrate helper takes it automatically (purchases
--   already holds applied schema). After this applies cleanly it prunes the
--   older pre-migration backup per the "one .bak per database" rule.

-- +migrate up

CREATE TABLE candidate_scores (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    criterion_id INTEGER NOT NULL REFERENCES criteria(id) ON DELETE CASCADE,
    score        REAL NOT NULL,
    notes        TEXT NOT NULL DEFAULT '',
    UNIQUE (candidate_id, criterion_id)
) STRICT;

CREATE INDEX idx_candidate_scores_candidate ON candidate_scores(candidate_id);
CREATE INDEX idx_candidate_scores_criterion ON candidate_scores(criterion_id);

-- +migrate down

DROP TABLE candidate_scores;
