# Dark theme tune

Make the dark theme easier on the eyes at night without losing contrast on tables.

## Interview

### Goal

Sam: the dark theme is too blue and the table stripes disappear after 10pm.

### Scope

From disk: one stylesheet, `base.css`, owns every surface colour.

### Out

Sam: no per-page overrides.

## Files

- Edit `static/css/base.css` (surface and stripe tokens)
- Create `static/css/theme-dusk.css` (the new palette)
- Test `tests/test_theme_tokens.py` (contrast of every token pair)

## Check

1. Every text token passes 4.5:1 on its surface.
2. Table stripes differ by at least 6 lightness points.
3. The old theme still loads when the dusk file is removed.

## Explicitly not built

- A theme picker: one palette ships, the switch stays where it is.
- Per-page colours: they drift.
