"""Daily online refresh of Kolkata's localities, colonies and neighbourhoods into the geo_places table (owner, 2026-11-04: "take online kolkata ... place names colony names, keep in db
and load daily once in cache").

WHAT IT DOES. Once a day (and once at launch when the last run is over a day old) it asks OpenStreetMap's Overpass API for every named suburb / neighbourhood / quarter / locality
inside Kolkata, and inserts each one this table does not hold yet as a geo_place of the Kolkata district, with its Bengali name (name:bn) as the Bengali alias. geo_service then loads the
rows into its in-memory gazetteer (a cache that rebuilds when the row counts change, geo_service._geo).

WHAT IT NEVER DOES (the truth boundary of geo_service). It never deletes or overwrites a row, and it gives the places NO police station: OpenStreetMap does not say which station covers a
colony, and a station is never guessed. A failed download changes nothing and is retried at the next hour check.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import geo_service
from db import SessionLocal
from models import GeoDistrict, GeoPlace, GeoPoliceStation

log = logging.getLogger("clinic-api.geo_loader")

OVERPASS_URL = os.environ.get("GEO_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
USER_AGENT = "KolkataCareVoicebot-geo-loader/1.0 (clinic address matching)"  # Overpass answers 406 to a request with none
STATE_PATH = os.environ.get("GEO_LOADER_STATE", "/tmp/geo_loader_state.json")
REFRESH_EVERY_S = 24 * 3600
QUERY = (
    '[out:json][timeout:90];area["name"="Kolkata"]["boundary"="administrative"]->.a;'
    '(node(area.a)["place"~"^(suburb|neighbourhood|quarter|locality|town|village)$"]["name"];'
    'way(area.a)["place"~"^(suburb|neighbourhood|quarter|locality)$"]["name"];);out tags center;'
)


MIRRORS = (OVERPASS_URL, "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter", OVERPASS_URL)  # the public servers are often busy: 502 / timeouts


def fetch_elements(timeout: float = 100.0) -> list[dict]:
    last: Exception | None = None
    for url in MIRRORS:
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode({"data": QUERY}).encode(),
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 -- a fixed https endpoint
                return json.loads(r.read().decode("utf-8")).get("elements", [])
        except Exception as e:
            last = e
    raise last or RuntimeError("no Overpass mirror answered")


def _key(name: str) -> str:
    return re.sub(r"[^\w]", "", (name or "").lower())


def load_into(db, elements: list[dict]) -> int:
    """Insert the localities in `elements` that the tables lack. Returns how many rows were added."""
    kolkata = db.query(GeoDistrict).filter(GeoDistrict.code == "DIST_04").first()
    if kolkata is None:
        return 0
    known: set[str] = set()
    for row in list(db.query(GeoPlace).filter(GeoPlace.district_id == kolkata.id)) + list(db.query(GeoPoliceStation).filter(GeoPoliceStation.district_id == kolkata.id)):
        known.add(_key(geo_service.short_name(row.name)))
        for blob in (row.aliases_en, row.aliases_bn):
            known.update(_key(a) for a in (blob or "").split("|") if a)
    have_codes = {c for (c,) in db.query(GeoPlace.code).filter(GeoPlace.code.like("OSM_%"))}
    added = 0
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name:en") or tags.get("name") or "").strip()
        bn = (tags.get("name:bn") or "").strip()
        code = f"OSM_{el.get('type', 'n')[0]}{el.get('id')}"
        if not name or code in have_codes:
            continue
        keys = {_key(name), _key(bn)} - {""}
        if keys & known:
            continue
        known |= keys
        db.add(GeoPlace(code=code, district_id=kolkata.id, police_station_id=None, name=name, place_type=tags.get("place", ""), aliases_en=(tags.get("name") if tags.get("name") != name else "") or "", aliases_bn=bn, aliases_hi=""))
        added += 1
    db.commit()
    if added:
        geo_service.invalidate()
    return added


def _last_run() -> float:
    try:
        return float(json.load(open(STATE_PATH)).get("at", 0))
    except Exception:
        return 0.0


def refresh_if_due(force: bool = False) -> int | None:
    """One refresh when the last successful run is over a day old (or `force`). None = not due or the download failed; else the number of rows added."""
    if not force and time.time() - _last_run() < REFRESH_EVERY_S:
        return None
    try:
        elements = fetch_elements()
    except Exception as e:  # network, rate limit, bad JSON: nothing changes, retried at the next check
        log.warning("geo refresh skipped: %s", e)
        return None
    db = SessionLocal()
    try:
        added = load_into(db, elements)
    finally:
        db.close()
    try:
        json.dump({"at": time.time(), "elements": len(elements), "added": added}, open(STATE_PATH, "w"))
    except OSError:
        pass
    log.info("geo refresh: %d localities downloaded, %d new rows", len(elements), added)
    return added


def start_background(check_every_s: int = 3600) -> threading.Thread:
    def run() -> None:
        time.sleep(60)  # let the API finish starting first
        while True:
            try:
                refresh_if_due()
            except Exception:
                log.exception("geo refresh failed")
            time.sleep(check_every_s)

    t = threading.Thread(target=run, name="geo-loader", daemon=True)
    t.start()
    return t
