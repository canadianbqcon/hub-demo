-- +migrate up
-- Low boy fill becomes a COUNTED survey rather than a binary checklist.
--
-- The barback walks the low boy and taps each row to cycle 0-1-2-3-0, where the
-- number is how many of that product to grab from downstairs. 0 means nothing
-- needed. The tally then drives a sweep list grouped by storage area, so a
-- restock is one trip per area instead of running back and forth.
--
-- No new column: checklist_run_item.state is already TEXT and already carries a
-- per-kind state machine (duty -> open/done, stock -> open/good/low/out). This
-- adds a third machine, fill -> "0"/"1"/"2"/"3", validated in db.py the same way
-- the other two are. Flipping the template's kind is the whole change.
--
-- Existing lowboy_fill runs keep their rows; any in-flight run still holding
-- 'open'/'done' is normalized to '0' so no row is left in a state its new kind
-- does not recognize.

UPDATE checklist_template SET kind = 'fill' WHERE key = 'lowboy_fill';

UPDATE checklist_run_item
   SET state = '0'
 WHERE state NOT IN ('0', '1', '2', '3')
   AND run_id IN (
       SELECT r.id FROM checklist_run r
       JOIN checklist_template t ON t.id = r.template_id
       WHERE t.key = 'lowboy_fill'
   );

-- +migrate down
UPDATE checklist_run_item
   SET state = CASE WHEN state = '0' THEN 'open' ELSE 'done' END
 WHERE run_id IN (
       SELECT r.id FROM checklist_run r
       JOIN checklist_template t ON t.id = r.template_id
       WHERE t.key = 'lowboy_fill'
   );

UPDATE checklist_template SET kind = 'duty' WHERE key = 'lowboy_fill';
