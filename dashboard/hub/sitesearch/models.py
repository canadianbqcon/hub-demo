"""Result shapes shared by every sitesearch adapter."""

import re
from dataclasses import dataclass, field


@dataclass
class Listing:
    site: str
    title: str
    price: float | None
    currency: str
    condition: str
    url: str
    extra: dict = field(default_factory=dict)


@dataclass
class Post:
    site: str
    subreddit: str
    title: str
    body: str
    score: int
    num_comments: int
    created: str
    url: str
    id: str


@dataclass
class Comment:
    post_id: str
    body: str
    score: int
    depth: int
    created: str
    url: str


@dataclass
class SiteResult:
    site: str
    status: str  # ok | blocked | no_key | error
    rows: list
    note: str
    url: str | None = None


def terms(query: str) -> list[str]:
    """Lowercase, delete every character that is not a letter, digit or space
    (so "men's" -> "mens", "Beta-LT" -> "betalt"), then split on whitespace.
    A comma or hyphen between words is replaced by a space first so
    "Beta-LT, men's" -> ["beta", "lt", "mens"]."""
    q = re.sub(r"[-,/_]", " ", query.lower())
    q = re.sub(r"[^\w\s]", "", q)
    return q.split()


def title_matches(title: str, query: str) -> bool:
    """True when every query term appears in the title (punctuation-stripped)."""
    words = set(terms(title))
    return all(t in words for t in terms(query))
