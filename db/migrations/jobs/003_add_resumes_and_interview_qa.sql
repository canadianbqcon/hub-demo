-- +migrate up

CREATE TABLE resumes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    file_path      TEXT NOT NULL,
    variant        TEXT NOT NULL DEFAULT '',
    label          TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    created        TEXT NOT NULL DEFAULT (date('now')),
    updated        TEXT NOT NULL DEFAULT (date('now'))
) STRICT;

CREATE TABLE interview_qa (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id     INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    source_template_id INTEGER REFERENCES interview_qa(id) ON DELETE SET NULL,
    question_type      TEXT NOT NULL DEFAULT 'behavioral',
    question           TEXT NOT NULL,
    answer             TEXT NOT NULL DEFAULT '',
    notes              TEXT NOT NULL DEFAULT '',
    is_template        INTEGER NOT NULL DEFAULT 0,
    sort_order         INTEGER NOT NULL DEFAULT 0,
    created            TEXT NOT NULL DEFAULT (date('now')),
    updated            TEXT NOT NULL DEFAULT (date('now'))
) STRICT;

-- +migrate down
DROP TABLE interview_qa;
DROP TABLE resumes;
