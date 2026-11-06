-- Migration 002_debt_terms for cards.db
-- Generated: 2026-07-27
--
-- Purpose: the /finances debt tab needs the interest math inputs that until now
-- lived only as prose in wiki/facts/financial-snapshot-2026.md — APR, credit
-- limit, promotional 0% window, minimum payment. YNAB supplies the live balance
-- and nothing else; cards.db already owns the "everything YNAB won't tell us"
-- role for due dates, so the terms belong here too.
--
-- Installment loans (the My Chase Loan) are modelled as rows in this same table
-- with kind='loan' rather than a second table: they carry a balance, an APR and
-- a payment, which is every field a card has. What makes them different is two
-- columns — `parent` (their balance is carved OUT of the parent card's YNAB
-- balance, so the projection must subtract to avoid double-counting) and
-- `fixed_payment` (a contractual installment, not a floating minimum).

-- +migrate up

ALTER TABLE card ADD COLUMN kind          TEXT NOT NULL DEFAULT 'card';  -- 'card' | 'loan'
ALTER TABLE card ADD COLUMN apr           REAL;      -- ongoing purchase APR, percent (26.24 = 26.24%)
ALTER TABLE card ADD COLUMN promo_apr     REAL;      -- promotional APR percent while promo_end is in the future
ALTER TABLE card ADD COLUMN promo_end     TEXT;      -- ISO date the promo rate expires; NULL = no promo
ALTER TABLE card ADD COLUMN credit_limit  REAL;      -- NULL when unknown; drives utilization
ALTER TABLE card ADD COLUMN min_payment   REAL;      -- floor payment per cycle; NULL = derive from balance
ALTER TABLE card ADD COLUMN fixed_payment REAL;      -- loans: contractual installment per cycle
ALTER TABLE card ADD COLUMN term_months   INTEGER;   -- loans: remaining/total billing cycles
ALTER TABLE card ADD COLUMN parent        TEXT;      -- loans: card whose YNAB balance contains this one
ALTER TABLE card ADD COLUMN balance       REAL;      -- manual fallback when YNAB has no matching account

-- +migrate down

ALTER TABLE card DROP COLUMN kind;
ALTER TABLE card DROP COLUMN apr;
ALTER TABLE card DROP COLUMN promo_apr;
ALTER TABLE card DROP COLUMN promo_end;
ALTER TABLE card DROP COLUMN credit_limit;
ALTER TABLE card DROP COLUMN min_payment;
ALTER TABLE card DROP COLUMN fixed_payment;
ALTER TABLE card DROP COLUMN term_months;
ALTER TABLE card DROP COLUMN parent;
ALTER TABLE card DROP COLUMN balance;
