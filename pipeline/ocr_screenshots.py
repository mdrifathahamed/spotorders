"""Read courier-history screenshots uploaded from the app and add their tasks to orders_raw.csv.

The app's "Add history screenshot" button puts images in screenshots/ of the private data repo.
Each new image is read with Tesseract OCR (free, runs inside GitHub Actions). The history page
looks like this:

    26 NOV 2026
    €37.94
    K-Supermarket Arabia                13:55
    Task offer (1.49 km)                €3.50
    McDonald's Helsinki Teollisuuskatu, Mashiro Vallila    11:31     <- stacked order, 2 pickups
    Task offer (3.27 km)                €8.25

Venue names are snapped to names already known (to undo small OCR errors); a new venue is
placed at the OpenStreetMap food place that shares a word with its name and lies nearest to
where the GPS track put me at that minute. If the tasks on a page do not add up to the day
total, the page is flagged as partial (scroll and upload the rest).

Private output: rows appended to orders_raw.csv, derived/ocr_report.csv,
screenshots/processed.txt (images already read).
"""
from __future__ import annotations

import csv
import difflib
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from .geo import haversine_m

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private"
SHOTS = PRIVATE / "screenshots"
MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}

DATE_RE = re.compile(r"\b(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{4})\b", re.I)
VENUE_RE = re.compile(r"^(?P<venue>[A-Za-z0-9ÅÄÖåäöéü&'’.,\-–()/ +]+?)\s+(?P<time>[0-2]?\d[:.][0-5]\d)$")
TASK_RE = re.compile(r"(?P<kind>[A-Za-z ]*?)\(?\s*(?P<km>\d+(?:[.,]\d+)?)\s*km\)?\s*[€Ee]\s?(?P<eur>\d+[.,]\d{2})")
TIP_RE = re.compile(r"\btip\b.*?[€Ee]\s?(?P<eur>\d+[.,]\d{2})", re.I)
TOTAL_RE = re.compile(r"^[€Ee]\s?(\d+[.,]\d{2})$")
GRILL = "The Grill - Pizza, Kebab & Burger"
STOP = {"ravintola", "restaurant", "helsinki", "kebab", "pizza", "burger", "sushi", "cafe", "kahvila", "the", "and"}


def ocr(path: Path) -> str:
    return subprocess.run(["tesseract", str(path), "-", "--psm", "4"], capture_output=True, text=True).stdout


def num(s: str) -> float:
    return float(s.replace(",", "."))


def parse(text: str, fallback_date: str | None):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    date, total = None, None
    for l in lines:
        m = DATE_RE.search(l)
        if m and date is None:
            date = f"{int(m.group(3)):04d}-{MONTHS[m.group(2)[:3].upper()]:02d}-{int(m.group(1)):02d}"
        m = TOTAL_RE.match(l)
        if m and total is None:
            total = num(m.group(1))
    tasks, cur = [], None
    for l in lines:
        mv = VENUE_RE.match(l)
        mt = TASK_RE.search(l)
        mtip = TIP_RE.search(l)
        if mv and not mt:
            cur = dict(time=mv.group("time").replace(".", ":").zfill(5), venue=mv.group("venue").strip(" ,"))
        elif mt and cur is not None:
            cur.update(distance_km=num(mt.group("km")), pay_eur=num(mt.group("eur")), tip_eur=0.0)
            tasks.append(cur)
            cur = None
        elif mtip and tasks:
            tasks[-1]["tip_eur"] = round(tasks[-1]["tip_eur"] + num(mtip.group("eur")), 2)
    return (date or fallback_date), total, tasks, date is None


def known_venues() -> list[str]:
    names = set(pd.read_csv(ROOT / "data/reference/venues.csv").venue)
    raw = pd.read_csv(PRIVATE / "orders_raw.csv")
    for v in raw.venue.dropna():
        names.update(split_venues(v))
    return sorted(names)


def split_venues(v: str) -> list[str]:
    return [GRILL if x == "THE_GRILL" else x for x in v.replace(GRILL, "THE_GRILL").split(", ")]


def snap(name: str, known: list[str]) -> str:
    m = difflib.get_close_matches(name, known, n=1, cutoff=0.88)
    return m[0] if m else name


def geocode_new(venue: str, date: str, time: str) -> dict | None:
    """Place a new venue at the OSM food place sharing a name word, nearest to my GPS at that minute."""
    try:
        osm = pd.read_csv(ROOT / "data/reference/osm_food_places.csv")
        from .track import load_track
        tr = load_track(PRIVATE)
    except Exception:
        return None
    areas = {a.lower() for a in pd.read_csv(ROOT / "data/reference/venues.csv").area.dropna()}
    places = set(re.findall(r"[a-zåäöé]{4,}", " ".join(areas))) | {"redi", "kamppi", "tripla", "citycenter", "sello"}
    words = {w for w in re.findall(r"[a-zåäöé]{4,}", venue.lower()) if w not in STOP | places}
    if not words or tr.empty:
        return None
    ts = pd.Timestamp(f"{date} {time}", tz="Europe/Helsinki")
    dt = (tr.ts - ts).abs()
    if dt.min() > pd.Timedelta(minutes=20):
        return None
    j = dt.idxmin()
    cand = osm[osm.name.fillna("").str.lower().apply(lambda n: bool(words & set(re.findall(r"[a-zåäöé]{4,}", n))))]
    if cand.empty:
        return None
    d = np.array([haversine_m(tr.lat[j], tr.lon[j], a, b) for a, b in zip(cand.lat, cand.lon)])
    k = int(d.argmin())
    if d[k] > 700:                    # I accept orders close to the venue; farther matches are wrong
        return None
    c = cand.iloc[k]
    return dict(venue=venue, lat=round(c.lat, 5), lon=round(c.lon, 5),
                address=f"{c['name']} (OpenStreetMap, nearest to GPS)", area="", geocode_quality="osm_auto")


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    done_f = SHOTS / "processed.txt"
    done = set(done_f.read_text().split()) if done_f.exists() else set()
    imgs = sorted(p for p in SHOTS.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.name not in done)
    if not imgs:
        print("ocr: no new screenshots")
        return
    raw = pd.read_csv(PRIVATE / "orders_raw.csv", dtype=str)
    have = set(zip(raw.date, raw.time, raw.venue))
    known = known_venues()
    venues = pd.read_csv(ROOT / "data/reference/venues.csv")
    new_rows, report, new_venues = [], [], []
    for p in imgs:
        m = re.search(r"(20\d{2})(\d{2})(\d{2})[_-]?(\d{6})?", p.name)
        fb = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
        stamp = (m.group(4) if m and m.group(4) else p.stem[-6:])
        date, total, tasks, date_guessed = parse(ocr(p), fb)
        added, unplaced = 0, []
        for t in tasks:
            parts = [snap(x, known) for x in split_venues(t["venue"])]
            venue = ", ".join(parts)
            key = (date, t["time"], venue)
            if date is None or key in have:
                continue
            have.add(key)
            new_rows.append([date, t["time"], venue, 1, f"{t['distance_km']:g}", f"{t['pay_eur']:.2f}",
                             f"{t['tip_eur']:g}", stamp])
            added += 1
            for v in parts:
                if v not in set(venues.venue) and v not in {n["venue"] for n in new_venues}:
                    g = geocode_new(v, date, t["time"])
                    if g:
                        new_venues.append(g)
                    else:
                        unplaced.append(v)
                    known.append(v)
        page_sum = round(sum(t["pay_eur"] + t["tip_eur"] for t in tasks), 2)
        report.append(dict(screenshot=p.name, date=date, date_from_filename=date_guessed, tasks_read=len(tasks),
                           tasks_added=added, page_total=total, tasks_sum=page_sum,
                           complete=(total is not None and abs(page_sum - total) < 0.01),
                           unplaced_venues="; ".join(unplaced)))
        done.add(p.name)
    if new_rows:
        with open(PRIVATE / "orders_raw.csv", "a", newline="") as f:
            csv.writer(f).writerows(new_rows)
    if new_venues:
        pd.concat([venues, pd.DataFrame(new_venues)], ignore_index=True).to_csv(
            ROOT / "data/reference/venues.csv", index=False)
    (PRIVATE / "derived").mkdir(exist_ok=True)
    rep = pd.DataFrame(report)
    old = PRIVATE / "derived/ocr_report.csv"
    if old.exists():
        rep = pd.concat([pd.read_csv(old), rep], ignore_index=True)
    rep.to_csv(old, index=False)
    done_f.write_text("\n".join(sorted(done)) + "\n")
    print(f"ocr: {len(imgs)} screenshot(s), {len(new_rows)} new task(s), {len(new_venues)} new venue(s)")
    print(pd.DataFrame(report).to_string(index=False))


if __name__ == "__main__":
    main()
