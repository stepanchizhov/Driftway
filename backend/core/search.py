"""
Place search.

Turns what a parent types - a postcode, a street, "the swimming pool" - into a
resolved coordinate they have explicitly chosen. Nothing routes until they pick
a result: guessing at free text would silently drive someone to the wrong town.

This lives on the backend rather than in the PWA so the TomTom key stays on the
server. A key shipped to the browser is a key anyone can lift from devtools.

Providers mirror the routing adapter pattern in router.py:
  - MockSearch:   a handful of fixed places, so the app runs with no key.
  - TomTomSearch: Fuzzy Search, verified against the live UK dataset.

Verified against api.tomtom.com/search/2 on 9 Sep 2026:
  - "SL4 1NJ" and "sl41nj" both resolve; the endpoint is already tolerant of
    spacing and case, and we normalise anyway so the label reads properly.
  - A full postcode returns type "Extended Postal Point"; a postcode district
    returns type "Geography" with entityType "PostalCodeArea". That entityType
    is what separates "an exact place" from "somewhere in this postcode".
  - address.postalCode holds only the outward code ("SL4"), NOT the full
    postcode. The full one is inside freeformAddress. Do not build labels from
    address.postalCode.
  - A POI search can return the same place several times, metres apart
    (four hits for one leisure centre), so results need de-duplicating.
  - No matches is HTTP 200 with numResults 0, not an error status.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List, Optional, Protocol
from urllib.parse import quote

import httpx

log = logging.getLogger("driftway")

from .geometry import haversine_km
from .models import Coord, Place

# Searching every index gives postcodes, streets, addresses and POIs in one
# call. EPP (Extended Postal Points) is the one that makes full UK postcodes
# resolve to a point rather than a district.
_IDX_SET = "PAD,Addr,Str,Geo,POI,EPP"

_SEARCH_BASE = "https://api.tomtom.com/search/2/search"

# Two results this close together, with the same address text, are the same
# place listed twice.
_DEDUPE_KM = 0.15

# UK postcode, spaces optional, either case. Deliberately permissive: this only
# decides how to tidy the string for display, never whether to search for it.
_POSTCODE_RE = re.compile(
    r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\s*$", re.IGNORECASE
)


def default_country() -> str:
    """Country set used only when the caller gives no position.

    SEARCH_DEFAULT_COUNTRIES, comma-separated ISO codes, default "GB".
    """
    return (os.getenv("SEARCH_DEFAULT_COUNTRIES") or "GB").strip() or "GB"


def normalise_query(raw: str) -> str:
    """Tidy a UK postcode into its canonical spacing and case.

    "sl41nj", "SL4 1NJ" and " sl4  1nj " are the same postcode; a parent
    thumbing one into a phone should not have to care. Anything that is not a
    postcode is passed through untouched.
    """
    m = _POSTCODE_RE.match(raw or "")
    if m:
        return f"{m.group(1).upper()} {m.group(2).upper()}"
    return (raw or "").strip()


def _classify(result: dict) -> tuple:
    """Map a TomTom result onto our own (kind, approximate) pair.

    `approximate` drives the "this is an area, want to be more precise?" hint,
    so it must be true for anything that is a centroid rather than a place.
    """
    rtype = (result.get("type") or "").lower()
    entity = (result.get("entityType") or "").lower()

    if entity == "postalcodearea":
        return "postcode_area", True
    if rtype == "extended postal point":
        return "postcode", False
    if rtype == "point address":
        return "address", False
    if rtype == "address range":
        return "address", True
    if rtype == "street" or rtype == "cross street":
        return "street", True
    if rtype == "poi":
        return "poi", False
    if rtype == "geography":
        return "place", True
    return "place", True


def _split_label(result: dict) -> tuple:
    """Produce the two lines the picker shows.

    The primary line names the thing; the secondary line carries enough address
    to tell two similarly named results apart, which is the whole reason the
    picker shows two lines.
    """
    address = result.get("address") or {}
    freeform = address.get("freeformAddress") or ""
    poi_name = ((result.get("poi") or {}).get("name") or "").strip()

    if poi_name:
        return poi_name, freeform
    if freeform:
        # "5 Stovell Road, Windsor, SL4 5JB" -> "5 Stovell Road" + the rest.
        head, _, tail = freeform.partition(", ")
        return (head or freeform), (tail or freeform)
    return "Unnamed place", ""


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, near: Optional[Coord], limit: int) -> List[Place]:
        ...


# --------------------------------------------------------------------------
# Mock implementation
# --------------------------------------------------------------------------

# Enough real places around the test area to exercise the picker with no key.
_MOCK_PLACES = [
    ("Windsor Leisure Centre", "Stovell Road, Windsor, SL4 5JB", 51.4857, -0.6214, "poi"),
    ("Windsor Castle", "Castle Hill, Windsor, SL4 1NJ", 51.4839, -0.6065, "poi"),
    ("Saint Leonard's Road", "Windsor, SL4 3BJ", 51.4759, -0.6136, "street"),
    ("Datchet", "Slough Road, Datchet, SL3 9AZ", 51.4855, -0.5790, "place"),
    ("Eton High Street", "Eton, SL4 6AF", 51.4890, -0.6080, "street"),
]


class MockSearch:
    name = "mock"

    async def search(self, query: str, near: Optional[Coord], limit: int) -> List[Place]:
        q = (query or "").strip().lower()
        if not q:
            return []
        out: List[Place] = []
        for i, (label, detail, lat, lng, kind) in enumerate(_MOCK_PLACES):
            haystack = f"{label} {detail}".lower()
            if q in haystack or any(tok in haystack for tok in q.split()):
                out.append(Place(
                    id=f"mock-{i}",
                    label=label,
                    detail=detail,
                    coord=Coord(lat=lat, lng=lng),
                    kind=kind,
                    approximate=kind in ("street", "place"),
                ))
        return out[:limit]


# --------------------------------------------------------------------------
# TomTom implementation
# --------------------------------------------------------------------------

class TomTomSearch:
    name = "tomtom"

    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None):
        if not api_key:
            raise ValueError("TomTom API key is required for TomTomSearch")
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=8.0)

    async def search(self, query: str, near: Optional[Coord], limit: int) -> List[Place]:
        clean = normalise_query(query)
        if len(clean) < 2:
            return []

        params = {
            "key": self._key,
            "typeahead": "true",       # predictive: the user is still typing
            "limit": min(max(limit * 2, limit), 20),  # room to dedupe, then trim
            "idxSet": _IDX_SET,
            "language": "en-GB",
        }
        if near is not None:
            # Bias toward the parent: someone in Windsor searching "High
            # Street" means the local one. With a position to bias by, no
            # country restriction - it used to be fixed to GB, which made the
            # search return nothing at all for testers in Berlin.
            params["lat"] = f"{near.lat:.6f}"
            params["lon"] = f"{near.lng:.6f}"
            params["radius"] = 60000
        else:
            # No position: keep to the default country rather than offering a
            # "High Street" from the other side of the world.
            params["countrySet"] = default_country()

        url = f"{_SEARCH_BASE}/{quote(clean)}.json"
        try:
            resp = await self._client.get(url, params=params)
        except httpx.HTTPError as e:
            # Deliberately does not log the query: it is someone's address.
            log.warning("TomTom search transport error: %s", type(e).__name__)
            raise SearchUnavailable("Could not reach the address search.") from e

        if resp.status_code in (401, 403):
            log.error("TomTom search %s: key rejected or Search not enabled",
                      resp.status_code)
            raise SearchUnavailable("Address search is not configured correctly.")
        if resp.status_code == 429:
            raise SearchUnavailable("Address search is busy. Try again in a moment.")
        if resp.status_code >= 400:
            log.warning("TomTom search HTTP %s", resp.status_code)
            raise SearchUnavailable("Address search failed.")

        try:
            body = resp.json()
        except ValueError as e:
            raise SearchUnavailable("Address search returned an unreadable reply.") from e

        return _to_places(body.get("results") or [], limit)


def _to_places(results: List[dict], limit: int) -> List[Place]:
    places: List[Place] = []
    for res in results:
        position = res.get("position") or {}
        lat, lon = position.get("lat"), position.get("lon")
        if lat is None or lon is None:
            continue
        coord = Coord(lat=lat, lng=lon)
        label, detail = _split_label(res)
        kind, approximate = _classify(res)

        # Collapse the duplicate POI entries TomTom returns for one venue.
        if any(p.label == label and haversine_km(p.coord, coord) < _DEDUPE_KM
               for p in places):
            continue

        places.append(Place(
            id=str(res.get("id") or f"{lat:.5f},{lon:.5f}"),
            label=label,
            detail=detail,
            coord=coord,
            kind=kind,
            approximate=approximate,
        ))
        if len(places) >= limit:
            break
    return places


class SearchUnavailable(RuntimeError):
    """The provider could not answer. Distinct from 'no matches', which is a
    normal, empty, successful result."""


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def get_search() -> SearchProvider:
    provider = os.getenv("SEARCH_PROVIDER", os.getenv("ROUTING_PROVIDER", "mock")).lower()
    if provider == "tomtom":
        key = os.getenv("TOMTOM_API_KEY", "").strip()
        if not key:
            log.warning(
                "search provider is tomtom but TOMTOM_API_KEY is empty; "
                "using the built-in sample places instead"
            )
            return MockSearch()
        return TomTomSearch(api_key=key)
    return MockSearch()
