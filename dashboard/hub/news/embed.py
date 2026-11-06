"""Title embeddings from the local Ollama server, for grouping re-worded headlines.

Every failure degrades to None for the affected titles; callers fall back to
token-Jaccard. NEWS_EMBED_OFF=1 turns the whole thing off (tests set it).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import urllib.request

import numpy as np

MODEL = "granite-embedding:278m"
DIMS = 768
CHUNK = 64
TIMEOUT = 30.0
URL = "http://localhost:11434/api/embed"


def _post(payload: dict, timeout: float) -> dict:
    """The one HTTP call; tests replace it."""
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _clean(raw) -> np.ndarray | None:
    """One reply vector -> unit float32, or None if it is malformed."""
    try:
        v = np.asarray(raw, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if v.shape != (DIMS,) or not np.isfinite(v).all():
        return None
    norm = float(np.linalg.norm(v))
    if not math.isfinite(norm) or norm == 0.0:
        return None
    return (v / norm).astype(np.float32)


def embed(titles: list[str]) -> list[np.ndarray | None]:
    """One entry per title, None where its chunk failed or embedding is off."""
    if os.environ.get("NEWS_EMBED_OFF") == "1":
        return [None] * len(titles)
    from news import cluster  # cluster imports this module at top level
    texts = [cluster._strip_outlet_suffix(t) for t in titles]
    out: list[np.ndarray | None] = []
    for i in range(0, len(texts), CHUNK):
        chunk = texts[i:i + CHUNK]
        try:
            vecs = _post({"model": MODEL, "input": chunk}, TIMEOUT)["embeddings"]
            if not isinstance(vecs, list) or len(vecs) != len(chunk):
                raise ValueError("wrong embedding count")
            cleaned = [_clean(v) for v in vecs]
            if any(v is None for v in cleaned):
                raise ValueError("bad embedding")
        except Exception:
            cleaned = [None] * len(chunk)
        out.extend(cleaned)
    return out


def store(conn: sqlite3.Connection, item_id: int, vec) -> None:
    blob = np.asarray(vec).astype("<f4").tobytes()
    conn.execute(
        "INSERT OR REPLACE INTO item_vectors (item_id, model, vec) VALUES (?, ?, ?)",
        (item_id, MODEL, blob),
    )


def load(conn: sqlite3.Connection, item_ids) -> dict[int, np.ndarray]:
    """Vectors for the given items, current model only."""
    ids = list(item_ids)
    out: dict[int, np.ndarray] = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        marks = ",".join("?" * len(part))
        for item_id, blob in conn.execute(
            f"SELECT item_id, vec FROM item_vectors WHERE model = ? AND item_id IN ({marks})",
            [MODEL, *part],
        ):
            out[item_id] = np.frombuffer(blob, dtype="<f4").astype(np.float32)
    return out
