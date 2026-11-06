-- 008_order_delivery_address.sql — where the parcel is going.
--
-- Nothing on an order said where it was being delivered, so the orders side
-- pane had no pin to draw. The address is the field; the two coordinates are
-- its cache, filled at write time by the same Nominatim helper trips uses for
-- a guest's home, so a saved address has a point on it immediately instead of
-- waiting for a pass that may never run. An address that cannot be placed
-- keeps its text and loses only its pin.

-- +migrate up

ALTER TABLE orders ADD COLUMN delivery_address TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN delivery_lat REAL;
ALTER TABLE orders ADD COLUMN delivery_lng REAL;

-- +migrate down

ALTER TABLE orders DROP COLUMN delivery_lng;
ALTER TABLE orders DROP COLUMN delivery_lat;
ALTER TABLE orders DROP COLUMN delivery_address;
