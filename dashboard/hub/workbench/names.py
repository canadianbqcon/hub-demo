"""Short names for the build list: one Haiku call names every uncached build title
in 2 to 4 words (the terminal-title idea), cached in vault data/workbench/short-titles.json
keyed by the full title, so each title costs one call ever. No key or a failed call
returns only what is cached and the page keeps its own trimmed title.

Self-check: python3 names.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MODEL = "claude-haiku-5-5"
MAX_TITLES = 200      # per request; the page sends one per build
MAX_LEN = 300         # a title longer than this is not a doc title
# measured 2026-10-12: the list's title column is 180px of 13px semibold, ~23 average
# characters; 22 leaves room for wide letters. Re-measure if the list width changes.
FIT = 22
PROMPT = (
    "Each line below is the title of a software build document (a spec, plan or a design "
    f"question). Give each a short name for a sidebar row that fits {FIT} characters, like a "
    f"terminal tab title: the thing being built, not the question about it. Up to {FIT} characters, "
    "never more; a short name stays short, never pad one to use the room. Plain "
    "words, no punctuation, no quotes, sentence case. Answer with only a JSON array of strings, "
    "one per line, in the same order.\n\n"
)


def _cache_path(root=None) -> Path:
    if root is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from vault_path import vault_root  # noqa: E402
        root = vault_root()
    return Path(root) / "data" / "workbench" / "short-titles.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _save(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _api_key() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "finances"))
    from autocat import _api_key as key  # noqa: E402  (same key lookup as the book's autocat)  # pyright: ignore[reportMissingImports]  autocat lives in ../finances, added to sys.path on the line above
    return key()


def parse(text: str, n: int):
    """n names from the model's JSON array, None in place of one that does not fit;
    None for the whole answer when it is not an array of n."""
    m = re.search(r"\[.*\]", text or "", re.S)
    try:
        out = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(out, list) or len(out) != n:
        return None
    out = [re.sub(r"\s+", " ", str(s)).strip(" .\"'") for s in out]
    return [s if 0 < len(s) <= FIT else None for s in out]


def _ask(titles: list[str]):
    key = _api_key()
    if not key:
        return None
    import anthropic
    resp = anthropic.Anthropic(api_key=key).messages.create(
        # low effort: naming needs no thinking, and thinking ate a tight max_tokens whole
        model=MODEL, max_tokens=4096, output_config={"effort": "low"},
        messages=[{"role": "user", "content": PROMPT + "\n".join(titles)}])
    return parse("".join(b.text for b in resp.content if b.type == "text"), len(titles))


def short_names(titles, root=None, ask=_ask) -> dict:
    """{title: short name} for every title we have a name for. ponytail: no lock; two
    tabs naming the same titles at once both write the same answers."""
    titles = [t for t in dict.fromkeys(titles) if isinstance(t, str) and 0 < len(t) <= MAX_LEN][:MAX_TITLES]
    path = _cache_path(root)
    cache = _load(path)
    missing = [t for t in titles if t not in cache]
    if missing:
        # two tries: the second asks again only for names that came back too long
        for _ in range(2):
            try:
                names = ask(missing) or []
            except Exception as e:
                print(f"workbench names: {e!r}", file=sys.stderr)
                names = []
            got = {t: s for t, s in zip(missing, names, strict=False) if s}
            cache.update(got)
            missing = [t for t in missing if t not in got]
            if not missing:
                break
        _save(path, cache)
    return {t: cache[t] for t in titles if t in cache}


if __name__ == "__main__":
    import tempfile
    assert parse('["Hub mark mode", "Trip intake form"]', 2) == ["Hub mark mode", "Trip intake form"]
    assert parse('Sure: ["a b"]', 1) == ["a b"]
    assert parse('["one"]', 2) is None and parse("no json", 1) is None
    assert parse('["ok", "' + "x" * 23 + '"]', 2) == ["ok", None]   # one long name drops only itself
    with tempfile.TemporaryDirectory() as d:
        calls = []
        def fake(ts):
            calls.append(ts)
            return [t.split()[0] for t in ts]
        assert short_names(["Alpha beta", "Gamma delta"], d, fake) == {"Alpha beta": "Alpha", "Gamma delta": "Gamma"}
        assert short_names(["Alpha beta", "Eps"], d, fake) == {"Alpha beta": "Alpha", "Eps": "Eps"}
        assert calls == [["Alpha beta", "Gamma delta"], ["Eps"]]   # cached titles are never re-asked
        assert short_names(["Zeta"], d, lambda ts: None) == {}      # a failed call caches nothing
        tries = []
        def retry(ts):
            tries.append(ts)
            return [None if len(tries) == 1 and t == "Eta" else t for t in ts]
        assert short_names(["Eta", "Iota"], d, retry) == {"Eta": "Eta", "Iota": "Iota"}
        assert tries == [["Eta", "Iota"], ["Eta"]]                  # the retry asks only the long one
        assert short_names(["x" * 400, 5], d, fake) == {}           # junk input is dropped
    print("ok")
