# Dark theme tune Implementation Plan

**Goal:** Ship the dusk palette behind the existing theme switch.

**Architecture:** One small change per file, tested before the next.

**Runs as:** inline

### Task 1: Palette tokens ~6k

Summary: Write the surface, stripe and text tokens.

**Files:**
- Create: `static/css/theme-dusk.css`

- [ ] **Step 1: Pick the surface ladder** Do it and confirm it by running the test for this task.
- [ ] **Step 2: Write the tokens** Do it and confirm it by running the test for this task.
- [ ] **Step 3: Run the contrast test** Do it and confirm it by running the test for this task.

### Task 2: Wire the switch ~4k

Summary: Point the theme switch at the new file.

**Files:**
- Edit: `static/css/base.css`

- [ ] **Step 1: Edit the loader** Do it and confirm it by running the test for this task.
- [ ] **Step 2: Check the old theme still loads** Do it and confirm it by running the test for this task.

### Task 3: Screens ~3k

Summary: Check the stripes on the three busiest tables.

**Files:**
- Edit: `tests/test_theme_tokens.py`

- [ ] **Step 1: Open each table** Do it and confirm it by running the test for this task.
- [ ] **Step 2: Compare against the spec** Do it and confirm it by running the test for this task.
