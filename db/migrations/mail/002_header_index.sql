-- +migrate up
-- Covering index for the list routes (mail/api.py _threads and the label
-- counts). label_ids is stored after body_html, so a table scan reads every
-- body's overflow pages (~230 MB, 11 s on /mnt/c); this index holds the header
-- columns, so list queries never touch the bodies.
CREATE INDEX IF NOT EXISTS idx_message_header ON message(
    account_id, internal_date, id, thread_id, from_addr, from_name, subject, snippet, label_ids
);

-- +migrate down
DROP INDEX IF EXISTS idx_message_header;
