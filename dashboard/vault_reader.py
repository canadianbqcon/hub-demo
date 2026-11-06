from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import frontmatter

logger = logging.getLogger(__name__)


@dataclass
class Node:
    path: str
    type: str
    summary: str
    tags: list[str]
    confidence: str
    created: str
    updated: str
    relationships: list[dict]
    body: str
    title: str
    status: str = ""
    name: str = ""
    email: str = ""
    aliases: list[str] = field(default_factory=list)
    travel_prefs: dict = field(default_factory=dict)


class VaultReader:
    def __init__(self, wiki_path: Path, subdirs: list[str] | None = None):
        """`subdirs` limits the initial parse to those folders under wiki/.

        The whole wiki is 433 nodes and ~1.6s to parse off /mnt/c; a caller that
        only ever reads one type (trips wants contacts) was paying all of it for
        14 files. Paths stay relative to the vault root either way, so
        get_node("wiki/contacts/x.md") works the same under a restricted reader.
        """
        self.wiki_path = wiki_path
        self._subdirs = subdirs
        self._index: dict[str, Node] = {}
        self._lock = threading.Lock()
        self._load_all()

    def _load_all(self):
        roots = [self.wiki_path / d for d in self._subdirs] if self._subdirs else [self.wiki_path]
        for root in roots:
            for md_file in root.rglob("*.md"):
                self._parse_and_index(md_file)

    def _parse_and_index(self, file_path: Path):
        try:
            post = frontmatter.load(str(file_path))
            rel_path = str(file_path.relative_to(self.wiki_path.parent))

            rels = post.metadata.get("relationships", []) or []
            relationships = []
            if isinstance(rels, list):
                for item in rels:
                    if isinstance(item, dict):
                        relationships.extend(
                            {"edge": k, "target": v} for k, v in item.items()
                        )

            raw_tags = post.metadata.get("tags", []) or []
            if isinstance(raw_tags, str):
                raw_tags = [t.strip() for t in raw_tags.split(",")]
            elif not isinstance(raw_tags, list):
                # a bare YAML scalar (tags: 2024) is neither str nor list; wrap it
                # so the comprehension below can't raise and drop the whole node.
                raw_tags = [raw_tags]

            raw_aliases = post.metadata.get("aliases", []) or []
            if isinstance(raw_aliases, str):
                raw_aliases = [a.strip() for a in raw_aliases.split(",") if a.strip()]
            elif not isinstance(raw_aliases, list):
                raw_aliases = [raw_aliases]
            raw_prefs = post.metadata.get("travel_prefs", {}) or {}

            node = Node(
                path=rel_path,
                type=str(post.metadata.get("type", "note")),
                summary=str(post.metadata.get("summary", "")),
                tags=[str(t) for t in raw_tags],
                confidence=str(post.metadata.get("confidence", "n/a")),
                created=str(post.metadata.get("created", "")),
                updated=str(post.metadata.get("updated", "")),
                relationships=relationships,
                body=post.content,
                title=file_path.stem.replace("-", " ").title(),
                status=str(post.metadata.get("status", "")),
                name=str(post.metadata.get("name", "")),
                email=str(post.metadata.get("email", "")),
                aliases=[str(a) for a in raw_aliases],
                travel_prefs=raw_prefs if isinstance(raw_prefs, dict) else {},
            )
            with self._lock:
                self._index[rel_path] = node
        except Exception:
            # Log parse failures instead of swallowing them — silent failures hide
            # real issues (e.g. YAML colon-space gotcha). See
            # wiki/problems/vault-reader-silent-yaml-parse-errors.md.
            logger.exception("parse failed for %s", file_path)

    def invalidate(self, file_path: Path):
        rel_path = str(file_path.relative_to(self.wiki_path.parent))
        if file_path.exists():
            self._parse_and_index(file_path)
        else:
            with self._lock:
                self._index.pop(rel_path, None)

    def get_node(self, path: str) -> Optional[Node]:
        with self._lock:
            return self._index.get(path)

    def get_nodes(
        self,
        types: list[str] | None = None,
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
    ) -> list[Node]:
        with self._lock:
            nodes = list(self._index.values())

        if types:
            nodes = [n for n in nodes if n.type in types]
        if tags_any:
            nodes = [n for n in nodes if any(t in n.tags for t in tags_any)]
        if tags_all:
            nodes = [n for n in nodes if all(t in n.tags for t in tags_all)]

        return sorted(nodes, key=lambda n: n.updated or n.created, reverse=True)

    def update_frontmatter(self, path: str, updates: dict) -> bool:
        abs_path = self.wiki_path.parent / path
        if not abs_path.exists():
            return False
        try:
            post = frontmatter.load(str(abs_path))
            post.metadata.update(updates)
            tmp = abs_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))
            os.replace(tmp, abs_path)
            return True
        except Exception:
            logger.exception("update_frontmatter failed for %s", path)
            return False

    def append_to_body(self, path: str, text: str) -> bool:
        abs_path = self.wiki_path.parent / path
        if not abs_path.exists():
            return False
        try:
            post = frontmatter.load(str(abs_path))
            body = post.content
            marker = "\n## See also"
            if marker in body:
                idx = body.index(marker)
                post.content = body[:idx] + f"\n\n{text}" + body[idx:]
            else:
                post.content = body + f"\n\n{text}"
            tmp = abs_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))
            os.replace(tmp, abs_path)
            return True
        except Exception:
            logger.exception("append_to_body failed for %s", path)
            return False

    def get_active_trip(self) -> Optional[Node]:
        with self._lock:
            nodes = list(self._index.values())
        active = [n for n in nodes if n.status == "active" and "travel" in n.tags]
        if active:
            return sorted(active, key=lambda n: n.updated or n.created, reverse=True)[0]
        travel_notes = [n for n in nodes if n.type == "note" and "travel" in n.tags]
        if travel_notes:
            return sorted(
                travel_notes, key=lambda n: n.updated or n.created, reverse=True
            )[0]
        return None

    def create_node(
        self,
        type: str,
        title: str,
        tags: list,
        summary: str,
        body: str,
        confidence: str = "medium",
    ) -> Optional[str]:
        folder_map = {
            "fact": "facts",
            "note": "notes",
            "decision": "decisions",
            "concept": "concepts",
            "pattern": "patterns",
            "source": "sources",
            "task": "tasks",
            "question": "questions",
            "contact": "contacts",
        }
        folder = folder_map.get(type, "notes")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        target_dir = self.wiki_path / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        abs_path = target_dir / f"{slug}.md"
        counter = 1
        while abs_path.exists():
            abs_path = target_dir / f"{slug}-{counter}.md"
            counter += 1
        today = datetime.now().strftime("%Y-%m-%d")
        post = frontmatter.Post(body)
        post.metadata = {
            "type": type,
            "created": today,
            "updated": today,
            "summary": summary,
            "tags": tags,
            "confidence": confidence,
            "relationships": [],
        }
        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))
            rel_path = str(abs_path.relative_to(self.wiki_path.parent))
            self._parse_and_index(abs_path)
            return rel_path
        except Exception:
            logger.exception("create_node failed for title=%r type=%r", title, type)
            return None

    def count(self) -> int:
        with self._lock:
            return len(self._index)
