-- 010_transaction_uid - transaction_memos points at book.db txn.uid, not a YNAB id.
-- Existing YNAB ids become 'ynab:<id>', which is how the book importer names them.

-- +migrate up

ALTER TABLE transaction_memos RENAME COLUMN ynab_transaction_id TO transaction_uid;
UPDATE transaction_memos SET transaction_uid = 'ynab:' || transaction_uid
 WHERE transaction_uid IS NOT NULL AND transaction_uid != '';

-- +migrate down

UPDATE transaction_memos SET transaction_uid = CASE
    WHEN transaction_uid LIKE 'ynab:%' THEN substr(transaction_uid, 6) ELSE NULL END
 WHERE transaction_uid IS NOT NULL;
ALTER TABLE transaction_memos RENAME COLUMN transaction_uid TO ynab_transaction_id;
