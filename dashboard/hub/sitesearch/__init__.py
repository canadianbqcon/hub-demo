"""Site search toolkit: one search() over Reddit, eBay, Amazon and known stores."""

from concurrent.futures import ThreadPoolExecutor

from . import amazon, ebay, reddit, stores
from .models import Comment, Listing, Post, SiteResult, terms, title_matches

__all__ = ["Comment", "Listing", "Post", "SiteResult", "terms", "title_matches", "search"]


def _known():
    return ["ebay", "ebay_sold", "amazon", "reddit", "reddit:<sub>"] + stores.names()


def _run(token, query, f):
    """One site; an adapter that raises becomes an error result."""
    try:
        if token == "ebay":
            return ebay.search(query, max_price=f.get("max_price"), condition=f.get("condition"),
                               newest=f.get("newest", False))
        if token == "ebay_sold":
            return ebay.sold(query)
        if token == "amazon":
            return amazon.search(query, max_price=f.get("max_price"))
        return stores.search(token, query, max_price=f.get("max_price"))
    except Exception as e:
        return SiteResult(token, "error", [], f"{type(e).__name__}: {e}")


def search(query, sites, **filters) -> list[SiteResult]:
    """Results in the order of `sites`. Commerce rows are title-filtered and sorted by price."""
    out = {}
    commerce = []
    for i, tok in enumerate(sites):
        if tok == "reddit" or tok.startswith("reddit:"):
            sub = tok.partition(":")[2] or None
            try:
                out[i] = reddit.search(query, sub)
            except Exception as e:
                out[i] = SiteResult(tok, "error", [], f"{type(e).__name__}: {e}")
        elif tok in ("ebay", "ebay_sold", "amazon") or tok in stores.names():
            commerce.append((i, tok))
        else:
            out[i] = SiteResult(tok, "error", [], f"unknown site {tok}; known: {', '.join(_known())}")
    if commerce:
        with ThreadPoolExecutor(len(commerce)) as ex:
            futs = [(i, tok, ex.submit(_run, tok, query, filters)) for i, tok in commerce]
            for i, _tok, fut in futs:
                r = fut.result()
                r.rows = sorted((x for x in r.rows if title_matches(x.title, query)),
                                key=lambda x: (x.price is None, x.price or 0))
                out[i] = r
    return [out[i] for i in range(len(sites))]
