"""The one fake persona every seeder module draws from.

Dates are never absolute: d(-1) is yesterday at reset time, t(-3) three hours
ago (see demo_mode._OFFSET). Stored text uses these tokens; the reset turns
them into real dates against the day it runs.
"""
NAME = "Sam Rivera"
FIRST = "Sam"
EMAIL = "sam.rivera@example.com"
PHONE = "(555) 010-0142"
CITY = "Chicago, IL"
HOME_AIRPORT = "ORD"
EMPLOYER = "Larkspur Labs"  # current day job
ROLE = "Operations Analyst"
RESTAURANT = "Juniper & Co"  # stands in for the real bar job
FRIENDS = ["Priya Nair", "Marcus Bell", "Elena Ortiz", "Dev Chandra", "Hana Mori", "Tom Okafor"]
TRIPS = [("Lisbon", "Portugal"), ("Denver", "United States")]
SEED = 20261106


def d(n: int, time: str | None = None) -> str:
    """Date token n days from the reset day, optionally with a fixed time."""
    tok = f"@d{n:+d}" if n else "@d0"
    return f"{tok} {time}" if time else tok


def t(hours: int) -> str:
    """Timestamp token n hours from the reset moment."""
    return f"@t{hours:+d}" if hours else "@t0"
