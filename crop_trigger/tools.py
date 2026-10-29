"""Weather-data tools: load a station CSV, profile it, and build a clean rainfall series in mm.

CSV columns: date (YYYY-MM-DD), rainfall, unit, station.
Everything is read as text first so that blanks, odd units and duplicates are detected instead of silently coerced.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

REQUIRED = ["date", "rainfall", "unit", "station"]
KNOWN_UNIT_LABELS = ("mm", "cm", "in")


class WeatherFileError(Exception):
    pass


def load_weather_csv(path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as e:  # unreadable / empty file
        raise WeatherFileError(f"cannot read {path}: {e}") from e
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise WeatherFileError(f"missing column(s) {missing}; expected {REQUIRED}")
    for c in REQUIRED:
        df[c] = df[c].astype(str).str.strip()
    return df


def profile(df: pd.DataFrame) -> dict:
    dates = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    return {
        "rows": int(len(df)),
        "stations": sorted(set(df["station"])),
        "units": sorted(set(u.lower() for u in df["unit"])),
        "first_date": None if dates.isna().all() else dates.min().date().isoformat(),
        "last_date": None if dates.isna().all() else dates.max().date().isoformat(),
        "unparseable_dates": int(dates.isna().sum()),
    }


def build_series(df: pd.DataFrame, factors: dict) -> tuple[dict, dict]:
    """Return ({date: Decimal mm}, issues). A day is left out of the series when it has no valid reading.

    A reading is invalid when: the date is unparseable, the value is blank / non-numeric / negative,
    the unit label is not in `factors`, or the day has two different readings (conflicting duplicates).
    """
    issues = {"conflicting_dates": [], "invalid_readings": 0, "deduped_days": 0, "unparseable_dates": 0,
              "converted": {}, "unsupported_units": {}}
    dates = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    issues["unparseable_dates"] = int(dates.isna().sum())
    by_day: dict[date, list[tuple[str, str]]] = {}
    for d, val, unit in zip(dates, df["rainfall"], df["unit"]):
        if pd.isna(d):
            continue
        by_day.setdefault(d.date(), []).append((val.strip(), unit.strip().lower()))
    series: dict = {}
    for day, rows in sorted(by_day.items()):
        distinct = set(rows)
        if len(distinct) > 1:
            issues["conflicting_dates"].append(day.isoformat())
            continue
        if len(rows) > 1:
            issues["deduped_days"] += 1
        val, unit = rows[0]
        if unit not in factors:
            issues["unsupported_units"][unit or "(blank)"] = issues["unsupported_units"].get(unit or "(blank)", 0) + 1
            issues["invalid_readings"] += 1
            continue
        try:
            x = Decimal(val)
        except InvalidOperation:
            issues["invalid_readings"] += 1
            continue
        if not x.is_finite() or x < 0:
            issues["invalid_readings"] += 1
            continue
        if unit != "mm":
            issues["converted"][unit] = issues["converted"].get(unit, 0) + 1
        series[day] = x * factors[unit]
    return series, issues
