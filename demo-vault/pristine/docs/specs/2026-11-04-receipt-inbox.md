# Receipt inbox

Drop a photo of a receipt and have it waiting beside the matching transaction.

## Interview

### Goal

Sam: paper receipts pile up before tax time.

### Open

Sam: unsure whether a photo should be read for line items.

## Files

- Create `finances/receipts.py`
- Edit `static/js/finance.jsx` (an attach button)

## Check

1. A receipt attaches to exactly one transaction.
2. A second attach asks before it replaces.

## Explicitly not built

- Reading line items: later, once the attach flow settles.
