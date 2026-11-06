# Product

## Register

product

## Users

A single operator (Sam) running his personal "second brain" over an Obsidian vault. Used mostly at a desktop, in two modes: a fast glance to read current status (today, schedule, cards, tasks), and focused drill-in to a workspace (jobs, trips, purchases, finances, work). The tool is a command center, not a consumer app — the user already knows what everything is and wants it surfaced precisely, not explained.

## Product Purpose

The Hub (Flask, port 5002) is the UI over the vault's data (`data/*.db`, JSON, wiki). It hosts a Home overview plus workspace modules, each a self-contained blueprint. Success is: the number he needs is on screen at a glance with no rounding, and any module opens into its task without ceremony.

## Brand Personality

Precise, quiet, senior-engineer calm. Information-dense without noise. Never cheery, gamified, or decorative. Voice is "a measured tool that disappears into the task," not "a friendly assistant."

## Anti-references

Generic SaaS dashboard slop: the hero-metric template (big number + gradient), purple/violet gradient heroes, glassmorphism-by-default, identical icon-heading-text card grids, tiny uppercase eyebrows over every section. No consumer gamification (streaks, confetti, badges). No abstract bucket labels ("Good / Fair / High") without the underlying scale.

## Design Principles

1. **At-a-glance or it failed.** Every surfaced value carries the scale that makes it readable; no abstract label stands alone.
2. **Exact cents, never rounded.** Money is shown to the cent. A rounded figure is a bug.
3. **The top bar is global.** One shared chrome across every module; change it once, it applies everywhere.
4. **Inherit the system, never invent.** Modules consume the existing token vocabulary and the theme matrix (vesper/cobalt/glass × dark/light). A per-module palette is wrong.
5. **Earned familiarity.** Standard affordances, consistent component vocabulary screen to screen. The tool should read as trustworthy to someone fluent in Linear/Notion/Raycast.

## Accessibility & Inclusion

WCAG AA contrast on body text (≥4.5:1) across all four theme×surface combinations. Reduced-motion respected on every transition. Visible keyboard focus. Motion stays in the 150–250ms band and conveys state, never decorates.
