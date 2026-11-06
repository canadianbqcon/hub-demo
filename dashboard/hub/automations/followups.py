"""Typed follow-ups for Sam's standing Gmail notes.

A note can select one fixed operation (craft_update, keep_until_superseded, ack_then_trash). Each is a
plain routine with its own allowlist. The email only picks which allowlisted target applies (the repo
name is matched from the subject against CRAFT_REPOS); nothing from an email body is executed,
downloaded from or passed to a shell.
"""

import json
import re
import sys

OPS = ("craft_update", "keep_until_superseded", "ack_then_trash")
MODEL = "claude-haiku-5-5"
CRAFT_REPOS = ["cadcraft", "deckcraft", "designcraft", "effectcraft", "filmcraft", "gridcraft",
               "lightcraft", "pdfcraft", "photocraft", "soundcraft", "vectorcraft", "wordcraft"]


SCOPES = ("once", "standing", "both")
JUDGE_TRIES = 3


def judge_note(client, note, item, pressed):
    """One Haiku call over his note and the email it was typed on. Returns {scope, op, rule_text}:
    scope once (this email only), standing (a rule about the sender) or both; rule_text is the
    standing part restated as a rule. None on a refusal, an unparseable answer or an API error."""
    ctx = (f"Email from {item.get('sender') or item.get('domain')}, subject {item.get('subject')!r},"
           f" kind {item.get('kind')!r}. Button pressed with the note: {pressed or 'none'}.")
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=300,
            system="Sam typed a note on one email in his inbox. Decide its reach from what it says: "
                   "once (an instruction about this one email only), standing (a rule for future mail from "
                   "this sender), or both. Restate any standing part as one short rule about the sender in "
                   "rule_text (empty for once). Also pick the one fixed operation the standing part selects: "
                   "craft_update (install the app update the release email announces), "
                   "keep_until_superseded (keep the newest, trash older ones once a newer one arrives), "
                   "ack_then_trash (show it, trash when he clicks Read), or none.",
            messages=[{"role": "user", "content": f"{ctx}\nNote: {note or ''}"}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
                "type": "object", "properties": {
                    "scope": {"type": "string", "enum": list(SCOPES)},
                    "op": {"type": "string", "enum": [*OPS, "none"]},
                    "rule_text": {"type": "string"}},
                "required": ["scope", "op", "rule_text"], "additionalProperties": False}}})
        got = json.loads(next(b.text for b in resp.content if b.type == "text"))
    except Exception as e:
        print(f"  judge_note failed: {e}", file=sys.stderr)
        return None
    if got.get("scope") not in SCOPES:
        return None
    op = got.get("op") if got.get("op") in OPS and got["scope"] != "once" else None
    return {"scope": got["scope"], "op": op, "rule_text": str(got.get("rule_text") or "").strip() or note}


def _rule_key(n):
    return f"{n['domain'] or '*'}|{n['kind'] or '*'}"


def propose_note_rule(conn, n, rule_text, op):
    """A proposed instruction rule for a note; a note whose old rule was settled gets a fresh identity."""
    from automations import rules
    ref = f"note:{n['id']}"
    if conn.execute("SELECT 1 FROM rule WHERE source='note' AND source_ref=? AND state IN ('proposed', 'confirmed')",
                    (ref,)).fetchone():
        return None
    if conn.execute("SELECT 1 FROM rule WHERE source='note' AND source_ref=?", (ref,)).fetchone():
        ref += "@" + rules._now()
    return rules.propose(conn, lane="gmail", rule_key=_rule_key(n), kind_of_rule="instruction",
                         source="note", source_ref=ref, note=rule_text, op=op)


def judge_pending(conn, client) -> int:
    """Judge every note not yet judged and under JUDGE_TRIES tries. A failure bumps tries and holds
    the note; standing and both propose a rule. No lock is held across the model call."""
    from automations import decisions
    n_done = 0
    for n in conn.execute("SELECT * FROM gmail_note WHERE active=1 AND scope IS NULL AND tries < ? ORDER BY id",
                          (JUDGE_TRIES,)).fetchall():
        item = conn.execute("SELECT * FROM gmail_item WHERE id=?", (n["item_id"],)).fetchone() if n["item_id"] else None
        got = judge_note(client, n["text"], dict(item) if item else {"domain": n["domain"], "kind": n["kind"]},
                         n["button"])
        with decisions.locked():
            if got is None:
                conn.execute("UPDATE gmail_note SET tries=tries+1 WHERE id=?", (n["id"],))
                conn.commit()
                continue
            # he may have picked a scope on /mail while the model ran; his pick wins
            if conn.execute("SELECT scope FROM gmail_note WHERE id=?", (n["id"],)).fetchone()[0] is not None:
                continue
            rid = propose_note_rule(conn, n, got["rule_text"], got["op"]) if got["scope"] != "once" else None
            conn.execute("UPDATE gmail_note SET scope=?, op=?, judged_at=?, rule_id=COALESCE(?, rule_id)"
                         " WHERE id=? AND scope IS NULL",
                         (got["scope"], got["op"], decisions._now(), rid, n["id"]))
            conn.commit()
        n_done += 1
    return n_done


def op_for(conn, domain, kind):
    """(op, (rule id, rev)) of the first confirmed instruction rule with an op for the sender, else None."""
    from automations import gmail_lane, rules
    for r in gmail_lane._rules_read(lambda: rules.confirmed(conn, "gmail", (domain, kind)), []):
        if r["kind_of_rule"] == "instruction" and r["op"]:
            return r["op"], (r["id"], r["rev"])
    return None


# ---- craft_update ----
# The install itself is the "Craft App Updater" scheduled task (automations/craft-updater/), which checks
# GitHub on its own as SYSTEM; the release email is only a notice, so this names the app and trashes it.

def _repo(subject):
    hits = [n for n in CRAFT_REPOS if re.search(rf"(?<![\w-]){n}(?![\w-])", subject or "", re.I)]
    return hits[0] if len(hits) == 1 else None


def craft_update(item):
    repo = _repo(item.get("subject"))
    if repo is None:
        return "wait", "no allowlisted app named in the subject"
    return "trash", f"{repo}: the Craft App Updater task installs it"


# ---- keep_until_superseded / ack_then_trash ----

def keep_until_superseded(conn, gmail, item, *, dry=False, ref=None):
    """Trash older kept mail of the same (domain, kind); the newest stays done KEEP."""
    from automations import gmail_lane
    older = [r for r in conn.execute(
        "SELECT id, msg_id, sender, reason, subject, kind FROM gmail_item WHERE domain=? AND kind IS ? AND"
        " action='KEEP' AND state='done' AND received_at < ? AND msg_id != ?",
        (item["domain"], item["kind"], item["received_at"], item["msg_id"])).fetchall()
        if not gmail_lane.security_like(r["kind"], r["subject"])]
    if dry:
        return "keep", f"would trash {len(older)} older kept"
    for r in older:
        try:
            live = gmail.users().messages().get(userId="me", id=r["msg_id"], format="minimal").execute()
        except Exception as e:  # a failed Gmail read skips this row; the next run looks again
            print(f"  gmail read failed: {e}", file=sys.stderr)
            continue
        have = live.get("labelIds", [])
        # left alone: a contact's mail, and anything he filed himself (out of the inbox or under a user label)
        if (gmail_lane.contact_match(gmail_lane.parseaddr(r["sender"] or "")[1], "") or "INBOX" not in have
                or any(lb.startswith("Label_") for lb in have)):
            continue
        old = {**item, "msg_id": r["msg_id"], "label_ids": have}
        if gmail_lane._dispatch(conn, gmail, old, r["id"], "trash", None, "superseded by a newer email",
                                from_state="done", refs=[ref] if ref else ()):  # a failed trash hands it back to done, never to waiting
            conn.execute("UPDATE gmail_item SET action='DELETE' WHERE id=?", (r["id"],))  # no longer a kept one
            conn.commit()
    return "keep", f"newest of its kind; {len(older)} older trashed" if older else "newest of its kind"


def run_followup(conn, gmail, item, op, *, dry=False, ref=None):
    """(verb, why) for the dispatcher, or None when the op is unknown."""
    if op == "craft_update":
        if dry:
            return "wait", "would run craft_update"
        return craft_update(item)
    if op == "keep_until_superseded":
        return keep_until_superseded(conn, gmail, item, dry=dry, ref=ref)
    if op == "ack_then_trash":
        return "wait", "waiting for your Read click, then trashed"
    return None
