-- 007_orders.sql — the things actually bought, as rows of their own.
--
-- Until now "what you bought" was eight columns on `decisions` (order_vendor,
-- order_number, order_placed, order_total, ship_status, carrier,
-- tracking_number, eta), which meant a purchase could only exist if it had
-- first been a research decision, and there was no way to see every parcel in
-- one place. `orders` is that store: one row per thing bought, decision_id
-- nullable so an ordinary purchase (or one lifted out of a confirmation email)
-- needs no decision at all. The decision columns stay on the table but stop
-- being read — the backfill below moves their content across.
--
-- `order_emails` is the dedupe ledger for the Gmail scan: one row per message
-- already folded into an order, so a re-scan is idempotent and a shipping
-- email can attach its tracking number to the order its receipt created.

-- +migrate up

-- The eight legacy order columns the backfill below reads were only ever created
-- by db.init()'s bootstrap ALTER block, never by a migration, so replaying the
-- purchases migrations from zero reached that SELECT against a decisions table
-- that had none of them. They are added here, immediately before the one
-- migration that reads them, so a from-scratch rebuild matches production.
ALTER TABLE decisions ADD COLUMN order_vendor    TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN order_number    TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN order_placed    TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN order_total     REAL;
ALTER TABLE decisions ADD COLUMN ship_status     TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN carrier         TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN tracking_number TEXT NOT NULL DEFAULT '';
ALTER TABLE decisions ADD COLUMN eta             TEXT NOT NULL DEFAULT '';

CREATE TABLE orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER REFERENCES decisions(id) ON DELETE SET NULL,
    item            TEXT NOT NULL,
    vendor          TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    image_url       TEXT NOT NULL DEFAULT '',
    order_number    TEXT NOT NULL DEFAULT '',
    ordered_on      TEXT NOT NULL DEFAULT '',
    total           REAL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    carrier         TEXT NOT NULL DEFAULT '',
    tracking_number TEXT NOT NULL DEFAULT '',
    -- ordered | shipped | out for delivery | delivered | returned | cancelled
    ship_status     TEXT NOT NULL DEFAULT 'ordered',
    eta             TEXT NOT NULL DEFAULT '',
    delivered_on    TEXT NOT NULL DEFAULT '',
    -- return window: days from delivery, or an explicit date that overrides it
    return_days     INTEGER,
    return_by       TEXT NOT NULL DEFAULT '',
    return_policy   TEXT NOT NULL DEFAULT '',
    returned_on     TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'manual',  -- manual | email | decision
    notes           TEXT NOT NULL DEFAULT '',
    created         TEXT NOT NULL DEFAULT (date('now')),
    updated         TEXT NOT NULL DEFAULT (date('now'))
) STRICT;

CREATE INDEX idx_orders_decision ON orders(decision_id);
CREATE INDEX idx_orders_status   ON orders(ship_status);

CREATE TABLE order_emails (
    message_id TEXT PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL DEFAULT '',   -- purchase | shipment
    sender     TEXT NOT NULL DEFAULT '',
    subject    TEXT NOT NULL DEFAULT '',
    received   TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE INDEX idx_order_emails_order ON order_emails(order_id);

-- Backfill: every decision that already carries order facts, or that has a
-- chosen winner, becomes an order. The item name is the winning candidate's
-- name where there is one, else the decision's. ship_status was free text
-- ("shipped - tracking issued 2026-09-01"), so anything outside the vocabulary
-- lands in notes and the row starts at 'ordered'.
INSERT INTO orders (decision_id, item, vendor, url, image_url, order_number,
                    ordered_on, total, currency, carrier, tracking_number,
                    ship_status, eta, source, notes)
SELECT d.id,
       COALESCE(c.name, d.name),
       COALESCE(NULLIF(d.order_vendor, ''), COALESCE(c.vendor, '')),
       COALESCE(c.url, ''),
       COALESCE(c.image_url, ''),
       d.order_number,
       d.order_placed,
       d.order_total,
       d.currency,
       d.carrier,
       d.tracking_number,
       CASE WHEN d.ship_status IN ('ordered','shipped','out for delivery',
                                   'delivered','returned','cancelled')
            THEN d.ship_status ELSE 'ordered' END,
       d.eta,
       'decision',
       CASE WHEN d.ship_status NOT IN ('','ordered','shipped','out for delivery',
                                       'delivered','returned','cancelled')
            THEN 'imported status: ' || d.ship_status ELSE '' END
FROM decisions d
LEFT JOIN candidates c ON c.id = d.verdict_candidate_id
WHERE d.verdict_candidate_id IS NOT NULL
   OR d.order_number <> '' OR d.order_vendor <> '' OR d.order_total IS NOT NULL
   OR d.tracking_number <> '' OR d.ship_status <> '';

-- +migrate down

DROP TABLE order_emails;
DROP TABLE orders;

ALTER TABLE decisions DROP COLUMN eta;
ALTER TABLE decisions DROP COLUMN tracking_number;
ALTER TABLE decisions DROP COLUMN carrier;
ALTER TABLE decisions DROP COLUMN ship_status;
ALTER TABLE decisions DROP COLUMN order_total;
ALTER TABLE decisions DROP COLUMN order_placed;
ALTER TABLE decisions DROP COLUMN order_number;
ALTER TABLE decisions DROP COLUMN order_vendor;
