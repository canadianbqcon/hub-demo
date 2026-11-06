"""No page zoom on phones and tablets, anywhere on the Hub (Sam's call, 2026-09-16).

The viewport tag alone does not do it: iOS Safari has ignored user-scalable=no
since iOS 10, so the pinch is also cancelled in script (gesture* events are
Safari's pinch) and double-tap zoom is turned off with touch-action. Maps keep
their own pinch: Leaflet and MapLibre read the raw touches before this
document-level handler cancels the browser's default.

Both the Hub and the public trips app run every HTML response through
lock_zoom, so a new template cannot miss it.
"""
import re

_VIEWPORT = re.compile(rb'<meta\s+name="viewport"[^>]*>', re.I)
_TAG = (
    b'<meta name="viewport" content="width=device-width, initial-scale=1, '
    b'maximum-scale=1, user-scalable=no, viewport-fit=cover">'
    b'\n<style>@media (pointer:coarse){html{touch-action:manipulation}}</style>'
    # Touch screens only: desktop Safari fires the same gesture events for a
    # trackpad pinch, and desktop keeps its zoom.
    b'\n<script>(function(){if(!matchMedia("(pointer:coarse)").matches)return;'
    b'var s=function(e){e.preventDefault()},o={passive:false};'
    b'["gesturestart","gesturechange","gestureend"].forEach(function(t){'
    b'document.addEventListener(t,s,o)});'
    b'document.addEventListener("touchmove",function(e){'
    b'if(e.touches.length>1)e.preventDefault()},o)})();</script>'
)


def lock_zoom(resp):
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if ctype != "text/html" or resp.status_code != 200:
        return resp
    resp.direct_passthrough = False   # send_from_directory hands back a file wrapper
    body = resp.get_data()
    if b"gesturestart" in body[:4096]:
        return resp
    body, n = _VIEWPORT.subn(lambda _: _TAG, body, count=1)
    if n:
        resp.set_data(body)
    return resp


if __name__ == "__main__":
    from flask import Response
    r = lock_zoom(Response(b'<head><meta name="viewport" content="width=device-width"></head>',
                           content_type="text/html"))
    out = r.get_data()
    assert b"user-scalable=no" in out and b"gesturestart" in out
    assert out.count(b'name="viewport"') == 1
    assert lock_zoom(r).get_data() == out            # idempotent
    j = lock_zoom(Response(b"{}", content_type="application/json"))
    assert j.get_data() == b"{}"
    print("zoom_lock ok")
