"""Demo stand-in: the real Hub watches its public repo's traffic; the demo has nothing to watch."""


def check(push: bool = True) -> dict:
    return {"outcome": "switched off in the demo"}
