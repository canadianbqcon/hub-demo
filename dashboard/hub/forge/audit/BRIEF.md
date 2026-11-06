# Forge trait audit brief (2026-11-03)

Goal: find where `bake_traits.py` rules give a wrong or missing trait value for a champion, using the wiki ability text as ground truth. You report findings only. You never edit `data/forge-traits.json`, `bake_traits.py` or any other file except your own output file.

## Inputs (vault = `/app/demo-vault`, code = `/app/dashboard/hub/forge`)

- Your champions: `code/judged/batches.json`, key = your batch number ("01".."09").
- Wiki abilities: `vault/data/forge-champions.json` -> `champions[<name>].abilities.value` (list of passive + Q/W/E/R, each with `text`, `notes`, `fields`, `ranks`).
- Current traits: `vault/data/forge-traits.json` -> `champions[<name>][<trait>]` (`value`, `source`, `basis`, `reason`, `raw`, `ability`; `damage10s.excluded` lists damage pieces the fight left out).
- Rules: `code/CLAUDE-draft.md` "Rubric rules" and `code/bake_traits.py` (`KEYWORDS` near line 1650, `keyword_row`, `rule_wall`, `TAG_FLAGS`). Read these first so your verdicts name the rule that failed.

Load JSON with a short python script that prints only your champions' rows; the files are large.

## What to check per champion

1. Every trait with `source: "unknown"` among: cleanse, globalPresence, vision, revive, execute, infiniteStacking, wallCrossing. Keyword rules give `unknown` when the keyword is absent (absence never proves false). Decide from the wiki text:
   - `present`: the kit has the mechanic. Quote the exact wiki line, name the ability, and say why the regex missed it (different wording, so `KEYWORDS[trait]` should add X; or the bin tooltip lacks it).
   - `absent`: the kit plainly lacks it. Say so in one line. This is information only, the rule stays `unknown`.
2. Every keyword trait that is `true` (computed): check the quoted `basis`/`raw` really means the mechanic (e.g. "vision" hit on an unrelated "wards" line, "execute" in flavor text). Report only false positives.
3. Every `damage10s.excluded` piece: say why it is excluded if the text shows it (no readable number, needs a stack, on a non-mana resource) and whether a handler could read it from the wiki text (quote the number line).
4. Anything else glaringly wrong you notice in the rubric traits (engage, peel, dive, dashes, unstoppable, untargetable, stealth, pets, terrain) against the text. Do not chase small numeric differences.

Never infer from memory of the game. Every `present` or `wrong` verdict carries a verbatim quote from `forge-champions.json`. No quote, no verdict: write `unclear`.

Do not spawn sub-agents. Before returning, re-open your output file and re-check five `present`/`false_positive` quotes against `forge-champions.json` verbatim.

## Output

Write `code/audit/batch-NN.json` (NN = your batch):

```json
{"batch": "01", "champions": {
  "Vayne": [
    {"trait": "execute", "current": "unknown", "verdict": "absent|present|false_positive|handler_missing|rule_wrong|unclear",
     "ability": "W", "quote": "verbatim wiki line", "fix": "one line: the rule or regex change that would catch it"}
  ]
}}
```

One entry per finding; `absent` verdicts may be grouped as `{"trait": "absent", "traits": [...]}` per champion to keep the file short. Return to the caller only: counts per verdict, and the ten most useful rule fixes (regex additions, handler gaps) seen across your batch.
