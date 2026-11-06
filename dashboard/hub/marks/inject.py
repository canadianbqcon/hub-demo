"""Injects the mark-mode loader into every Hub HTML page, like pull_refresh.

app.py's _ASSET_REF stamper adds the ?v= to the tag. Skipped for headless
re-renders (X-Hub-Render), the /marks/frame page, which carries its own
script, and the signed-out /login page. Fails open: any error returns the page untouched.
"""

from flask import request

_TAG = b'<script defer src="/static/js/marks.js"></script>'


def add_marks_script(resp):
    try:
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
        if ctype != "text/html" or resp.status_code != 200:
            return resp
        # /login is the one signed-out page: marks.js is signed-in only there (401).
        if (request.headers.get("X-Hub-Render") == "1"
                or request.path in ("/marks/frame", "/login")):
            return resp
        resp.direct_passthrough = False
        body = resp.get_data()
        if b"js/marks.js" in body:
            return resp
        # ponytail: last </body> by rfind, not an HTML parser; a page without one gets it appended
        i = body.lower().rfind(b"</body>")
        resp.set_data(body[:i] + _TAG + body[i:] if i >= 0 else body + _TAG)
        return resp
    except Exception:
        return resp
