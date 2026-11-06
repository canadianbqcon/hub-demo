# Weekly digest card

A single card on Home that sums up the week: spend, shifts worked, tasks closed.

## Interview

### Goal

Sam: one glance on Sunday night to see how the week went.

### Sources

From disk: tasks, shifts and the budget book already hold every number.

## Files

- Create `home/digest_card.py` (builds the week's numbers)
- Edit `static/js/home.jsx` (mount the card)
- Test `tests/test_digest_card.py`

## Check

1. A week with no shifts shows a dash, not zero hours.
2. Money is shown in the currency it was spent in.
3. The card loads in under 200 ms.

## Explicitly not built

- Email delivery: the card lives on the page only.
- Charts: three numbers and a sentence.
