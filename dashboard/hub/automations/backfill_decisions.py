"""One-off: write decision rows for work done before the decision log existed, so undo and fix reach it.
Every row carries reason 'reconstructed ...': Gmail before-labels are inferred from the live labels
(the target label or TRASH swapped for INBOX), finance before-values as uncategorized and unapproved.
`python -m automations.backfill_decisions` is a dry run; add --write to insert."""

import json
import os
import sys
from datetime import datetime, timezone

from . import db

TAG = "reconstructed: before the decision log"


def _gmail():
    sys.path.insert(0, os.path.expanduser("~/.config/vault-api"))
    import services
    return services.gmail_readonly()


def gmail_rows(conn, gmail):
    names = {lb["name"]: lb["id"] for lb in gmail.users().labels().list(userId="me").execute()["labels"]}
    out, skipped = [], []
    first = conn.execute("SELECT MIN(made_at) FROM decision").fetchone()[0] or "9"
    for it in conn.execute("SELECT * FROM gmail_item WHERE state IN ('done','moved') AND action IN ('MOVE','DELETE','UNSUBSCRIBE')"):
        if conn.execute("SELECT 1 FROM decision WHERE item_id=?", (it["id"],)).fetchone():
            continue
        when = datetime.fromisoformat(it["updated_at"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
        if when >= first:
            continue
        made_by = "auto" if it["run_id"] else "sam"
        base = dict(lane="gmail", ref=it["msg_id"], item_id=it["id"], made_at=when, made_by=made_by,
                    rule_key=f"{it['domain']}|{it['kind']}" if made_by == "auto" else None)
        if it["action"] == "UNSUBSCRIBE":
            out.append({**base, "action": "UNSUBSCRIBE", "changed": {"labels": [[], []]}, "undo": "none"})
            continue
        try:
            live = set(gmail.users().messages().get(userId="me", id=it["msg_id"], format="minimal").execute().get("labelIds", []))
        except Exception as e:
            skipped.append((it["id"], f"gone from Gmail: {e}"[:60]))
            continue
        target = "TRASH" if it["action"] == "DELETE" else names.get(it["label"])
        if not target or target not in live or "INBOX" in live:
            skipped.append((it["id"], f"live labels do not show the {it['action']}"))
            continue
        before = (live - {target}) | {"INBOX"}
        out.append({**base, "action": "trash" if it["action"] == "DELETE" else "move",
                    "changed": {"labels": [sorted(before), sorted(live)]},
                    "undo": "expires" if it["action"] == "DELETE" else "reversible"})
    return out, skipped


def finance_rows(conn):
    from finances import book
    done = {r[0] for r in conn.execute("SELECT ref FROM decision WHERE lane='finance-category'")}
    first = conn.execute("SELECT MIN(made_at) FROM decision").fetchone()[0] or "9"
    out = []
    with book._conn() as c:
        for t in c.execute("SELECT t.uid, t.category_id, t.suggested_at, t.payee_id FROM txn t WHERE t.suggested_confidence='high'"
                           " AND t.approved=1 AND t.deleted=0 AND t.category_id=t.suggested_category_id"):
            when = datetime.fromisoformat(str(t["suggested_at"]).replace("Z", "+00:00").replace(" ", "T"))
            when = (when if when.tzinfo else when.astimezone()).astimezone(timezone.utc).isoformat(timespec="seconds")
            if t["uid"] in done or when >= first:
                continue
            out.append(dict(lane="finance-category", ref=t["uid"], item_id=None, made_at=when, made_by="auto",
                            rule_key=None if t["payee_id"] is None else str(t["payee_id"]), action="categorize",
                            changed={"category_id": [None, t["category_id"]], "approved": [0, 1]}, undo="reversible"))
    return out


def write(conn, rows):
    for r in rows:
        conn.execute("INSERT INTO decision (lane, ref, item_id, rule_key, made_at, made_by, action, changed_json, state, undo, reason)"
                     " VALUES (?,?,?,?,?,?,?,?,'applied',?,?)",
                     (r["lane"], r["ref"], r["item_id"], r["rule_key"], r["made_at"], r["made_by"], r["action"],
                      json.dumps(r["changed"]), r["undo"], TAG))
    conn.commit()


if __name__ == "__main__":
    conn = db.connect()
    g, skipped = gmail_rows(conn, _gmail())
    f = finance_rows(conn)
    from collections import Counter
    print("gmail", Counter((r["action"], r["undo"], r["made_by"]) for r in g), "finance", len(f), "skipped", skipped)
    if "--write" in sys.argv:
        write(conn, g + f)
        print("wrote", len(g) + len(f))
