"""python3 -m sitesearch ... (run from dashboard/hub)."""

import argparse
import dataclasses
import json

from . import alerts, reddit, search, stores


def _cell(v):
    return str(v).replace("|", "/").replace("\n", " ")


def _table(rows):
    cols = [f.name for f in dataclasses.fields(rows[0]) if f.name != "extra"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(_cell(getattr(r, c)) for c in cols) + " |" for r in rows]
    return "\n".join(lines)


def _print(results):
    for r in results:
        if r.status == "ok":
            print(f"### {r.site}")
            print(_table(r.rows) if r.rows else "no results")
            print()
        else:
            print(f"{r.site}: {r.status} {r.note} {r.url or ''}".rstrip())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sitesearch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--sites", required=True)
    s.add_argument("--max-price", type=float)
    s.add_argument("--condition", choices=["new", "used"])
    s.add_argument("--json", action="store_true")
    sub.add_parser("comments").add_argument("post_id")
    d = sub.add_parser("discover")
    d.add_argument("store")
    d.add_argument("url")
    sv = sub.add_parser("save")
    sv.add_argument("query")
    sv.add_argument("--sites", required=True)
    sv.add_argument("--max-price", type=float)
    sub.add_parser("list")
    sub.add_parser("remove").add_argument("id")
    a = ap.parse_args(argv)

    if a.cmd == "search":
        res = search(a.query, [t for t in a.sites.split(",") if t],
                     max_price=a.max_price, condition=a.condition)
        if a.json:
            print(json.dumps([dataclasses.asdict(r) for r in res], indent=2))
        else:
            _print(res)
    elif a.cmd == "comments":
        _print([reddit.comments(a.post_id)])
    elif a.cmd == "discover":
        try:
            print(json.dumps(stores.discover(a.store, a.url)))
        except Exception as e:
            print(f"discover: error {type(e).__name__}: {e}")
    elif a.cmd == "save":
        sites = [t.strip() for t in a.sites.split(",") if t.strip()]
        bad = [t for t in sites if t not in alerts._alert_sites(",".join(sites))]
        if bad or not sites:  # these would be dropped silently at run time and the search never alert
            print(f"save: cannot alert on {', '.join(bad) or 'no sites'}; alert sites are ebay, "
                  "API-backed stores, and amazon only with KEEPA_KEY")
            return 2
        print(alerts.save(a.query, ",".join(sites), a.max_price))
    elif a.cmd == "list":
        for r in alerts.list_searches():
            print(f"{r['id']}\t{r['query']}\t{r['sites']}\t{r['max_price']}\t{'on' if r['active'] else 'off'}")
    else:
        if not alerts.remove(a.id):
            print(f"remove: no saved search {a.id}")
            return 1
    return 0
