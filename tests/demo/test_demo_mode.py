"""Demo layer cuts. Run from the export root:
DEMO_MODE=1 VAULT_PATH=<export>/demo-vault python3 -m pytest tests/demo/test_demo_mode.py -q
"""
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HUB = ROOT / "dashboard" / "hub"
assert os.environ.get("DEMO_MODE") == "1", "run with DEMO_MODE=1"
os.chdir(HUB)
sys.path.insert(0, str(HUB))
import app as hub_app  # noqa: E402
import demo_mode  # noqa: E402

app = hub_app.app


@pytest.fixture
def client():
    return app.test_client()


def demo_log():
    p = demo_mode.vault() / "demo.log"
    return p.read_text() if p.exists() else ""


def test_outside_connect_refused_and_logged():
    s = socket.socket()
    try:
        with pytest.raises(OSError):
            s.connect(("1.1.1.1", 443))
    finally:
        s.close()
    assert "refused connect ('1.1.1.1', 443)" in demo_log()


def test_outside_udp_send_refused():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(OSError):
            s.sendto(b"x", ("1.1.1.1", 53))
        with pytest.raises(OSError):
            s.sendmsg([b"x"], [], 0, ("1.1.1.1", 53))
        s.sendto(b"x", ("127.0.0.1", 9))  # loopback still allowed
    finally:
        s.close()
    assert "refused sendto ('1.1.1.1', 53)" in demo_log()


def test_outside_lookup_and_create_connection_refused():
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443), timeout=2)
    with pytest.raises(OSError):
        socket.getaddrinfo("example.com", 443)
    for f in (socket.gethostbyname, socket.gethostbyname_ex, socket.gethostbyaddr):
        with pytest.raises(OSError):
            f("example.com")
    assert socket.gethostbyname("localhost")


def test_loopback_allowed():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.socket()
    try:
        c.connect(srv.getsockname())
    finally:
        c.close()
        srv.close()


def test_processes_refused():
    with pytest.raises(OSError):
        subprocess.run(["ls"])
    with pytest.raises(OSError):
        os.system("true")


def test_node_transpile_allowed():
    import jsx_build
    src = next((HUB / "static").rglob("*.jsx"), None) or next(HUB.rglob("*.jsx"))
    assert jsx_build.transpile(src).strip()


def test_integration_route_403(client):
    r = client.post("/finances/api/book/sync")
    assert r.status_code == 403
    assert r.get_json()["demo"] == demo_mode.DEMO_MESSAGE


def test_path_escape_400(client):
    r = client.get("/finances/static/..%2F..%2Fapp.py")
    assert r.status_code == 400


def page_routes():
    out = []
    for rule in app.url_map.iter_rules():
        if ("GET" in rule.methods and not rule.arguments and "/api/" not in rule.rule
                and "static" not in rule.endpoint and not rule.rule.startswith("/apply")):
            out.append(rule.rule)
    return sorted(out)


def test_every_html_page_has_banner(client):
    pages = 0
    for path in page_routes():
        r = client.get(path)
        if r.status_code == 200 and r.mimetype == "text/html":
            pages += 1
            assert demo_mode.BANNER.encode() in r.get_data(), path
    assert pages >= 20


def test_healthz(client):
    assert client.get("/healthz").status_code == 200


def test_unclassified_route_fails_boot():
    from flask import Flask
    other = Flask("other")
    other.add_url_rule("/not-in-the-list", "x", lambda: "x")
    with pytest.raises(RuntimeError, match="unclassified"):
        demo_mode.check_endpoints(other)
