#!/usr/bin/env python3
"""Rebuild the Bangkok Inside Airbnb analysis using only Python's stdlib."""

from __future__ import annotations

import csv
import gzip
import html
import json
import math
import re
import sqlite3
from bisect import bisect_left, insort
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "outputs"
LISTINGS_FILE = RAW / "listings.csv.gz"
REVIEWS_FILE = RAW / "reviews.csv"
DB_FILE = PROCESSED / "bangkok.sqlite"


class MedianWindow:
    """SQLite median aggregate/window function with nulls ignored."""

    def __init__(self):
        self.values: list[float] = []

    def step(self, value):
        if value is not None:
            insort(self.values, float(value))

    def inverse(self, value):
        if value is not None:
            i = bisect_left(self.values, float(value))
            if i < len(self.values) and self.values[i] == float(value):
                self.values.pop(i)

    def value(self):
        n = len(self.values)
        if not n:
            return None
        if n % 2:
            return self.values[n // 2]
        return (self.values[n // 2 - 1] + self.values[n // 2]) / 2

    def finalize(self):
        return self.value()


def parse_price(value):
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value)).strip()
    if not cleaned or cleaned in {".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def number_or_null(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def db_connection():
    PROCESSED.mkdir(parents=True, exist_ok=True)
    if DB_FILE.exists():
        DB_FILE.unlink()
    conn = sqlite3.connect(DB_FILE)
    conn.create_window_function("MEDIAN", 1, MedianWindow)
    conn.create_function("parse_price", 1, parse_price)
    conn.create_function("number_or_null", 1, number_or_null)
    return conn


SOURCE_FIELDS = {
    "listing_id": "id",
    "host_id": "host_id",
    "neighborhood": "neighbourhood_cleansed",
    "room_type": "room_type",
    "bedrooms_raw": "bedrooms",
    "price_raw": "price",
    "estimated_occupancy_raw": "estimated_occupancy_l365d",
    "availability_365_raw": "availability_365",
    "reviews_ltm_raw": "number_of_reviews_ltm",
    "rating_raw": "review_scores_rating",
    "host_listing_count_raw": "calculated_host_listings_count",
    "latitude_raw": "latitude",
    "longitude_raw": "longitude",
    "last_review": "last_review",
    "last_scraped": "last_scraped",
}

def load_source(conn):
    if not LISTINGS_FILE.exists():
        raise FileNotFoundError(f"Missing {LISTINGS_FILE}; see README.md for download instructions.")
    defs = ", ".join(f"{field} TEXT" for field in SOURCE_FIELDS)
    conn.execute("DROP TABLE IF EXISTS listings_source")
    conn.execute(f"CREATE TABLE listings_source ({defs})")
    rows = []
    with gzip.open(LISTINGS_FILE, "rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [col for col in SOURCE_FIELDS.values() if col not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Missing expected source columns: {', '.join(missing)}")
        for row in reader:
            rows.append(tuple(row.get(source_col, "") for source_col in SOURCE_FIELDS.values()))
            if len(rows) >= 2_000:
                conn.executemany(
                    f"INSERT INTO listings_source VALUES ({','.join('?' for _ in SOURCE_FIELDS)})",
                    rows,
                )
                rows.clear()
        if rows:
            conn.executemany(
                f"INSERT INTO listings_source VALUES ({','.join('?' for _ in SOURCE_FIELDS)})",
                rows,
            )
    conn.commit()


def fetch_all(conn, query, params=()):
    cur = conn.execute(query, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def write_csv(path: Path, rows: list[dict], fieldnames=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def median_value(values):
    values = sorted(float(v) for v in values if v is not None)
    n = len(values)
    if not n:
        return None
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


def ranks(values):
    ordered = sorted((float(v), i) for i, v in enumerate(values))
    result = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][0] == ordered[start][0]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for _, index in ordered[start:end]:
            result[index] = average_rank
        start = end
    return result


def pearson(x, y):
    if len(x) < 2:
        return None
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denx = math.sqrt(sum((a - mx) ** 2 for a in x))
    deny = math.sqrt(sum((b - my) ** 2 for b in y))
    return None if denx == 0 or deny == 0 else numerator / (denx * deny)


def spearman(x, y):
    return pearson(ranks(x), ranks(y))


def crosscheck(neighborhoods):
    stable = [r for r in neighborhoods if r["listing_count"] >= 50]
    by_occ = sorted(stable, key=lambda r: (-r["median_occupancy_days"], r["neighborhood"]))
    by_reviews = sorted(stable, key=lambda r: (-r["median_reviews_ltm"], r["neighborhood"]))
    top_n = min(10, len(stable))
    top_occ = {r["neighborhood"] for r in by_occ[:top_n]}
    top_reviews = {r["neighborhood"] for r in by_reviews[:top_n]}
    return {
        "stable_neighborhoods_n": len(stable),
        "spearman_occupancy_vs_reviews_ltm": spearman(
            [r["median_occupancy_days"] for r in stable],
            [r["median_reviews_ltm"] for r in stable],
        ),
        "spearman_occupancy_vs_future_unavailable_share": spearman(
            [r["median_occupancy_days"] for r in stable],
            [r["median_unavailable_share_next_365d"] for r in stable],
        ),
        "top10_occupancy_review_overlap": len(top_occ & top_reviews),
        "top10_neighborhoods": top_n,
        "top10_occupancy_only": sorted(top_occ - top_reviews),
        "top10_reviews_only": sorted(top_reviews - top_occ),
    }


def build_seasonality(active_ids):
    if not REVIEWS_FILE.exists():
        return []
    counts = Counter()
    period_start = date(2025, 7, 1)
    period_end = date(2026, 6, 30)
    with REVIEWS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("listing_id") not in active_ids:
                continue
            raw_date = row.get("date", "")
            try:
                parsed = date.fromisoformat(raw_date[:10])
            except (TypeError, ValueError):
                continue
            if period_start <= parsed <= period_end:
                counts[parsed.strftime("%Y-%m")] += 1
    rows = []
    y, m = 2025, 7
    for _ in range(12):
        ym = f"{y:04d}-{m:02d}"
        rows.append({"month": ym, "review_count": counts[ym]})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return rows


def save_outputs(conn):
    OUT.mkdir(parents=True, exist_ok=True)

    counts = {
        "source_rows": conn.execute("SELECT COUNT(*) FROM listings_source").fetchone()[0],
        "missing_or_unparseable_price": conn.execute(
            "SELECT COUNT(*) FROM listings_typed WHERE price IS NULL"
        ).fetchone()[0],
        "zero_or_negative_price": conn.execute(
            "SELECT COUNT(*) FROM listings_typed WHERE price <= 0"
        ).fetchone()[0],
        "valid_positive_price_rows": conn.execute("SELECT COUNT(*) FROM listings_price_positive").fetchone()[0],
        "top_0_5_percent_price_outliers": conn.execute(
            "SELECT COUNT(*) FROM listings_price_positive"
        ).fetchone()[0] - conn.execute("SELECT COUNT(*) FROM listings_clean").fetchone()[0],
        "after_price_filters": conn.execute("SELECT COUNT(*) FROM listings_clean").fetchone()[0],
        "inactive_zero_ltm_reviews": conn.execute(
            "SELECT COUNT(*) FROM listings_clean WHERE reviews_ltm IS NULL OR reviews_ltm < 1"
        ).fetchone()[0],
        "active_final_rows": conn.execute("SELECT COUNT(*) FROM listings_active").fetchone()[0],
        "active_rows_missing_bedrooms": conn.execute(
            "SELECT COUNT(*) FROM listings_active WHERE bedrooms IS NULL"
        ).fetchone()[0],
        "active_rows_missing_rating": conn.execute(
            "SELECT COUNT(*) FROM listings_active WHERE rating IS NULL"
        ).fetchone()[0],
        "active_rows_missing_estimated_occupancy": conn.execute(
            "SELECT COUNT(*) FROM listings_active WHERE estimated_occupancy_days IS NULL"
        ).fetchone()[0],
    }
    removed_total = (
        counts["missing_or_unparseable_price"]
        + counts["zero_or_negative_price"]
        + counts["top_0_5_percent_price_outliers"]
        + counts["inactive_zero_ltm_reviews"]
    )
    counts["removed_total_sequential"] = removed_total
    counts["retained_share_of_source"] = counts["active_final_rows"] / counts["source_rows"]
    audit_rows = [
        {"step": "Source listings rows", "before": counts["source_rows"], "removed": 0, "retained": counts["source_rows"]},
        {"step": "Missing or unparseable price", "before": counts["source_rows"], "removed": counts["missing_or_unparseable_price"], "retained": counts["source_rows"] - counts["missing_or_unparseable_price"]},
        {"step": "Zero or negative price among price-present rows", "before": counts["source_rows"] - counts["missing_or_unparseable_price"], "removed": counts["zero_or_negative_price"], "retained": counts["valid_positive_price_rows"]},
        {"step": "Highest 0.5% of valid positive prices", "before": counts["valid_positive_price_rows"], "removed": counts["top_0_5_percent_price_outliers"], "retained": counts["after_price_filters"]},
        {"step": "No review in last 12 months", "before": counts["after_price_filters"], "removed": counts["inactive_zero_ltm_reviews"], "retained": counts["active_final_rows"]},
    ]
    write_csv(OUT / "cleaning_audit.csv", audit_rows)

    summaries = fetch_all(conn, "SELECT * FROM neighborhood_room_summary ORDER BY neighborhood, room_type")
    neighborhoods = fetch_all(conn, "SELECT * FROM neighborhood_summary ORDER BY neighborhood")
    pricing = fetch_all(conn, "SELECT * FROM pricing_gap_groups ORDER BY neighborhood, room_type, bedrooms")
    hosts = fetch_all(conn, "SELECT * FROM host_type_summary ORDER BY host_type")
    room_bedroom = fetch_all(
        conn,
        """SELECT room_type, bedrooms, COUNT(*) AS listing_count,
                  MEDIAN(price) AS median_price,
                  MEDIAN(estimated_occupancy_days) AS median_occupancy_days,
                  MEDIAN(reviews_ltm) AS median_reviews_ltm,
                  MEDIAN(rating) AS median_rating
           FROM listings_active
           WHERE bedrooms IS NOT NULL
           GROUP BY room_type, bedrooms
           ORDER BY room_type, bedrooms""",
    )
    city_occupancy = conn.execute("SELECT MEDIAN(estimated_occupancy_days) FROM listings_active").fetchone()[0]
    city_reviews = conn.execute("SELECT MEDIAN(reviews_ltm) FROM listings_active").fetchone()[0]
    city_price = conn.execute("SELECT MEDIAN(price) FROM listings_active").fetchone()[0]
    room_baselines = {
        r["room_type"]: {
            "listing_count": r["listing_count"],
            "median_nightly_price_thb": r["median_price"],
            "median_estimated_occupancy_days": r["median_occupancy_days"],
        }
        for r in fetch_all(
            conn,
            """SELECT room_type, COUNT(*) AS listing_count,
                      MEDIAN(price) AS median_price,
                      MEDIAN(estimated_occupancy_days) AS median_occupancy_days
               FROM listings_active GROUP BY room_type""",
        )
    }

    for row in summaries:
        row["opportunity_flag"] = "Other"
        if row["listing_count"] >= 20 and row["gap_listing_count"] >= 20:
            if row["underpriced_share"] is not None and row["underpriced_share"] >= 0.25 and row["median_occupancy_days"] > city_occupancy:
                row["opportunity_flag"] = "Underpriced and in demand"
            elif row["overpriced_share"] is not None and row["overpriced_share"] >= 0.25 and row["median_occupancy_days"] < city_occupancy:
                row["opportunity_flag"] = "Overpriced and weak"

    for row in pricing:
        row["opportunity_flag"] = "Other"
        if row["underpriced_share"] >= 0.25 and row["median_occupancy_days"] > city_occupancy:
            row["opportunity_flag"] = "Underpriced and in demand"
        elif row["overpriced_share"] >= 0.25 and row["median_occupancy_days"] < city_occupancy:
            row["opportunity_flag"] = "Overpriced and weak"

    write_csv(OUT / "neighborhood_room_summary.csv", summaries)
    write_csv(OUT / "pricing_gap_groups.csv", pricing)
    write_csv(OUT / "host_type_summary.csv", hosts)
    write_csv(OUT / "room_type_bedroom_summary.csv", room_bedroom)

    cross = crosscheck(neighborhoods)
    cross_rows = []
    occ_ranked = {r["neighborhood"]: i + 1 for i, r in enumerate(sorted(neighborhoods, key=lambda r: (-r["median_occupancy_days"], r["neighborhood"]))) if r["listing_count"] >= 50}
    rev_ranked = {r["neighborhood"]: i + 1 for i, r in enumerate(sorted(neighborhoods, key=lambda r: (-r["median_reviews_ltm"], r["neighborhood"]))) if r["listing_count"] >= 50}
    for row in neighborhoods:
        cross_rows.append({
            **row,
            "occupancy_rank_among_50_plus": occ_ranked.get(row["neighborhood"]),
            "reviews_rank_among_50_plus": rev_ranked.get(row["neighborhood"]),
        })
    write_csv(OUT / "demand_crosscheck.csv", cross_rows)

    min_supply_sample = 30
    stable_counts = sorted(r["listing_count"] for r in neighborhoods if r["listing_count"] >= min_supply_sample)
    q25_rank = max(1, math.ceil(0.25 * len(stable_counts)))
    low_supply_cutoff = stable_counts[q25_rank - 1] if stable_counts else None
    low_supply = [
        {**r, "supply_cutoff_25th_percentile": low_supply_cutoff}
        for r in neighborhoods
        if r["listing_count"] >= min_supply_sample
        and r["listing_count"] <= low_supply_cutoff
        and r["median_occupancy_days"] > city_occupancy
    ]
    low_supply.sort(key=lambda r: (-r["median_occupancy_days"], r["listing_count"]))
    write_csv(OUT / "high_demand_low_supply.csv", low_supply)

    flagged = [
        {**row, "city_median_occupancy_days": city_occupancy}
        for row in summaries
    ]
    write_csv(OUT / "neighborhood_room_opportunities.csv", flagged)

    season = build_seasonality({r[0] for r in conn.execute("SELECT listing_id FROM listings_active")})
    write_csv(OUT / "seasonality.csv", season, ["month", "review_count"])

    overview = {
        "snapshot_date": "2026-06-29",
        "scrape_date_min": conn.execute("SELECT MIN(last_scraped) FROM listings_active").fetchone()[0],
        "scrape_date_max": conn.execute("SELECT MAX(last_scraped) FROM listings_active").fetchone()[0],
        "source_rows": counts["source_rows"],
        "active_listings": counts["active_final_rows"],
        "median_nightly_price_thb": city_price,
        "median_estimated_occupancy_days": city_occupancy,
        "median_reviews_ltm": city_reviews,
        "room_type_baselines": room_baselines,
        "neighborhoods": len(neighborhoods),
        "room_neighborhood_groups": len(summaries),
        "pricing_gap_groups": len(pricing),
        "median_occupancy_city_baseline": city_occupancy,
        "median_neighborhood_supply_cutoff": low_supply_cutoff,
        "minimum_neighborhood_sample_for_supply_flag": min_supply_sample,
        "low_supply_neighborhoods": len(low_supply),
        "underpriced_in_demand_groups": sum(1 for r in flagged if r["opportunity_flag"] == "Underpriced and in demand"),
        "overpriced_weak_groups": sum(1 for r in flagged if r["opportunity_flag"] == "Overpriced and weak"),
        "demand_crosscheck": cross,
        "cleaning": counts,
    }
    with (OUT / "market_overview.json").open("w", encoding="utf-8") as f:
        json.dump(overview, f, indent=2, ensure_ascii=False)

    map_points = fetch_all(conn, "SELECT latitude, longitude FROM listings_active WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
    dashboard_data = {
        "overview": overview,
        "neighborhoods": neighborhoods,
        "room_groups": flagged,
        "pricing_groups": pricing,
        "hosts": hosts,
        "room_type_bedroom_summary": room_bedroom,
        "seasonality": season,
        "map_points": [[round(r["longitude"], 5), round(r["latitude"], 5)] for r in map_points],
    }
    write_dashboard(dashboard_data)

    with (OUT / "analysis_summary.json").open("w", encoding="utf-8") as f:
        json.dump({"overview": overview, "hosts": hosts, "room_type_bedroom_summary": room_bedroom, "low_supply": low_supply, "opportunities": flagged, "pricing": pricing, "seasonality": season}, f, indent=2, ensure_ascii=False)


def write_dashboard(data):
    safe_data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    safe_data = safe_data.replace("</", "<\\/")
    template = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bangkok Airbnb | Neighborhood opportunity</title>
<style>
:root{color-scheme:light;--ink:#172b36;--muted:#526873;--line:#cfdbdd;--paper:#fbfaf6;--surface:#fff;--teal:#0d6c68;--coral:#c85b3c;--sand:#e4d2b0;--soft:#eaf2ef;--gold:#c59b4b;font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink)}header{padding:28px clamp(18px,5vw,64px) 18px;border-bottom:1px solid var(--line)}.eyebrow{color:var(--teal);text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700}h1{font-family:Georgia,serif;font-weight:500;font-size:clamp(28px,4vw,44px);line-height:1.08;margin:6px 0 8px}header p{color:var(--muted);margin:0;max-width:760px}.tabs{display:flex;gap:8px;padding:16px clamp(18px,5vw,64px);border-bottom:1px solid var(--line);overflow:auto}.tab{font:inherit;color:var(--muted);background:transparent;border:0;border-bottom:2px solid transparent;padding:9px 12px;white-space:nowrap;cursor:pointer}.tab[aria-selected=true]{color:var(--teal);border-color:var(--teal);font-weight:650}main{padding:24px clamp(18px,5vw,64px) 44px;max-width:1500px;margin:auto}.panel[hidden]{display:none}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 22px}.metric{padding:14px 16px;border:1px solid var(--line);background:var(--surface);border-radius:9px}.metric span{display:block;color:var(--muted);font-size:13px}.metric strong{font-variant-numeric:tabular-nums;display:block;font-size:23px;font-weight:650;margin-top:3px}.section{margin-top:24px}.section h2{font-family:Georgia,serif;font-weight:500;font-size:25px;margin:0 0 6px}.section p{color:var(--muted);margin:0 0 12px;max-width:900px}.chart{width:100%;height:auto;display:block;background:#fff;border:1px solid var(--line);border-radius:8px}.axis{stroke:#9daeb0;stroke-width:1}.grid{stroke:#e3e9e6;stroke-width:1}.tick{font-size:11px;fill:#526873}.point{fill:var(--teal);fill-opacity:.38;stroke:var(--teal);stroke-opacity:.18}.bubble{fill:var(--coral);fill-opacity:.75;stroke:#fff;stroke-width:1}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:end;margin:14px 0}.controls label{display:grid;gap:4px;color:var(--muted);font-size:13px}.controls select,.controls input{font:inherit;border:1px solid var(--line);border-radius:6px;background:white;color:var(--ink);padding:8px 10px;min-width:150px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff}table{width:100%;border-collapse:collapse;min-width:760px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #e5ebea;font-variant-numeric:tabular-nums}th{position:sticky;top:0;background:#f1f5f2;color:var(--muted);font-size:12px;font-weight:650}td.num,th.num{text-align:right}.flag{display:inline-block;padding:2px 7px;border-radius:12px;background:#e7f1ed;color:#155a4d;font-size:12px}.flag.warn{background:#fae9e1;color:#8a3c25}.small{font-size:12px;color:var(--muted)}.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:8px}.swatch{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;background:var(--teal)}.swatch.coral{background:var(--coral)}footer{padding:18px clamp(18px,5vw,64px);border-top:1px solid var(--line);color:var(--muted);font-size:12px}.tooltip{position:fixed;pointer-events:none;display:none;background:#172b36;color:white;padding:7px 9px;border-radius:5px;font-size:12px;z-index:3;max-width:260px}.empty{color:var(--muted);padding:20px}@media(max-width:760px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding-top:18px}.metric strong{font-size:20px}}@media(max-width:430px){.metric{padding:10px}.metric strong{font-size:18px}.metrics{gap:8px}}
</style>
</head><body>
<header><div class="eyebrow">Inside Airbnb · Bangkok · 29 June 2026</div><h1>Where are hosts leaving money on the table?</h1><p>Active listings are priced against bedroom, room type and neighborhood peers. Demand is shown as review-based estimated occupied nights, with recent reviews as a second signal.</p></header>
<nav class="tabs" role="tablist" aria-label="Dashboard pages"><button class="tab" id="overview-tab" role="tab" aria-controls="overview" aria-selected="true">Market overview</button><button class="tab" id="opportunity-tab" role="tab" aria-controls="opportunity" aria-selected="false">Neighborhood opportunity</button><button class="tab" id="pricing-tab" role="tab" aria-controls="pricing" aria-selected="false">Pricing gap explorer</button></nav>
<main>
<section class="panel" id="overview" role="tabpanel" aria-labelledby="overview-tab"><div class="metrics" id="metric-row"></div><div class="section"><h2>Active listing locations</h2><p>Each dot marks an active listing with coordinates. Density shows where supply clusters; it does not show bookings.</p><div id="map"></div><div class="legend"><span><i class="swatch"></i>Active listing</span><span class="small">Longitude and latitude · point plot, not a street basemap</span></div></div><div class="section"><h2>Host type comparison</h2><p>Single-listing and multi-listing hosts, among listings with at least one review in the last 12 months.</p><div class="table-wrap"><table id="host-table"></table></div></div><div class="section"><h2>Recent review seasonality</h2><p>Guest review dates for active listings, by full calendar month from July 2025 through June 2026. Review dates can lag stays.</p><div id="season"></div></div></section>
<section class="panel" id="opportunity" role="tabpanel" aria-labelledby="opportunity-tab" hidden><div class="section"><h2>Neighborhood price and demand</h2><p>Each bubble is a neighborhood and room type. Bubble size is active listing count. Horizontal and vertical reference lines mark citywide medians.</p><div class="controls"><label>Room type<select id="scatter-room"><option value="All">All room types</option></select></label><label>Minimum active listings<input id="scatter-min" type="number" min="1" value="20"></label></div><div id="scatter"></div><div class="legend"><span><i class="swatch"></i>Neighborhood × room type</span><span class="small">Price and occupancy are medians. High occupancy is relative to this city snapshot.</span></div></div><div class="section"><h2>High-demand, lower-supply areas</h2><p>At least 30 active listings, occupancy above the city median, and supply in the bottom quartile among neighborhoods with at least 30 active listings. Treat these smaller markets cautiously.</p><div class="table-wrap"><table id="supply-table"></table></div></div></section>
<section class="panel" id="pricing" role="tabpanel" aria-labelledby="pricing-tab" hidden><div class="section"><h2>Comparable listing groups</h2><p>Each row compares listings in the same neighborhood, room type and bedroom count. Groups below 20 listings are suppressed. Shares show listings at least 20% below or above their peer median; median index is centered near 1 by construction.</p><div class="controls"><label>Room type<select id="filter-room"><option value="All">All room types</option></select></label><label>Bedrooms<select id="filter-bed"><option value="All">All bedroom counts</option></select></label><label>Neighborhood<input id="filter-neighborhood" type="search" placeholder="Search neighborhood"></label><label>Opportunity<select id="filter-flag"><option value="All">All results</option><option>Underpriced and in demand</option><option>Overpriced and weak</option><option>Other</option></select></label></div><p class="small" id="row-count" aria-live="polite"></p><div class="table-wrap"><table id="pricing-table"></table></div></div></section>
</main><footer>Source: Inside Airbnb, Bangkok detailed listings and reviews, 29 June 2026. CC BY 4.0. Prices are in Thai baht, the local currency; the dollar sign in the source export is a formatting artifact. Occupancy is model-estimated from review data. Future unavailability can be booked or host-blocked. Coordinates are anonymized and may be offset from the true address.</footer><div class="tooltip" id="tip" role="status"></div>
<script>
const D=__DATA__;
const fmt=(x,d=0)=>x==null?'—':Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const money=x=>x==null?'—':'฿'+fmt(x);
const pct=x=>x==null?'—':fmt(100*x,0)+'%';
const median=(a)=>{const v=a.filter(x=>x!=null).map(Number).sort((x,y)=>x-y),n=v.length;return n?(n%2?v[(n-1)/2]:(v[n/2-1]+v[n/2])/2):null};
const metric=(label,value)=>`<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
const panels=[...document.querySelectorAll('.panel')];
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.setAttribute('aria-selected',String(x===b)));panels.forEach(p=>p.hidden=p.id!==b.getAttribute('aria-controls'));}));
const O=D.overview;
document.getElementById('metric-row').innerHTML=[metric('Active listings',fmt(O.active_listings)),metric('Median nightly price',money(O.median_nightly_price_thb)),metric('Median estimated occupancy',fmt(O.median_estimated_occupancy_days)+' nights'),metric('Median reviews in last 12 months',fmt(O.median_reviews_ltm))].join('');
function axisSvg({title,w=900,h=500,plot={x:72,y:32,w:780,h:405},xmin,xmax,ymin,ymax,xticks,yticks,xlabel,ylabel}){let s=`<svg class="chart" role="img" aria-label="${title}" viewBox="0 0 ${w} ${h}"><title>${title}</title>`;for(const t of xticks){let x=plot.x+(t-xmin)/(xmax-xmin)*plot.w;s+=`<line class="grid" x1="${x}" y1="${plot.y}" x2="${x}" y2="${plot.y+plot.h}"/><text class="tick" x="${x}" y="${plot.y+plot.h+20}" text-anchor="middle">${fmt(t)}</text>`}for(const t of yticks){let y=plot.y+plot.h-(t-ymin)/(ymax-ymin)*plot.h;s+=`<line class="grid" x1="${plot.x}" y1="${y}" x2="${plot.x+plot.w}" y2="${y}"/><text class="tick" x="${plot.x-9}" y="${y+4}" text-anchor="end">${fmt(t)}</text>`}s+=`<line class="axis" x1="${plot.x}" y1="${plot.y+plot.h}" x2="${plot.x+plot.w}" y2="${plot.y+plot.h}"/><line class="axis" x1="${plot.x}" y1="${plot.y}" x2="${plot.x}" y2="${plot.y+plot.h}"/><text class="tick" x="${plot.x+plot.w/2}" y="${h-12}" text-anchor="middle">${xlabel}</text><text class="tick" transform="translate(18 ${plot.y+plot.h/2}) rotate(-90)" text-anchor="middle">${ylabel}</text>`;return {s,plot,w,h,xmin,xmax,ymin,ymax}}
function drawMap(){const pts=D.map_points, minx=Math.min(...pts.map(p=>p[0])),maxx=Math.max(...pts.map(p=>p[0])),miny=Math.min(...pts.map(p=>p[1])),maxy=Math.max(...pts.map(p=>p[1]));const w=1000,h=520,p={x:48,y:22,w:924,h:458};let s=`<svg class="chart" role="img" aria-label="Map-like point plot of ${fmt(pts.length)} active Bangkok listings" viewBox="0 0 ${w} ${h}"><title>Active listing locations by longitude and latitude</title><rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" fill="#f4f4ed"/>`;for(let i=0;i<=4;i++){let x=p.x+i*p.w/4,y=p.y+i*p.h/4;s+=`<line class="grid" x1="${x}" y1="${p.y}" x2="${x}" y2="${p.y+p.h}"/><line class="grid" x1="${p.x}" y1="${y}" x2="${p.x+p.w}" y2="${y}"/><text class="tick" x="${x}" y="${p.y+p.h+18}" text-anchor="middle">${fmt(minx+i*(maxx-minx)/4,2)}</text><text class="tick" x="${p.x-8}" y="${y+4}" text-anchor="end">${fmt(maxy-i*(maxy-miny)/4,2)}</text>`}for(const [x,y] of pts){const cx=p.x+(x-minx)/(maxx-minx)*p.w,cy=p.y+(maxy-y)/(maxy-miny)*p.h;s+=`<circle class="point" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="2.1"/>`}s+=`<text class="tick" x="${p.x+p.w/2}" y="${h-9}" text-anchor="middle">Longitude</text><text class="tick" transform="translate(14 ${p.y+p.h/2}) rotate(-90)" text-anchor="middle">Latitude</text></svg>`;document.getElementById('map').innerHTML=s}
drawMap();
function renderHost(){let rows=D.hosts;document.getElementById('host-table').innerHTML='<thead><tr><th>Host type</th><th class="num">Listings</th><th class="num">Median price</th><th class="num">Median rating</th><th class="num">Median estimated nights</th><th class="num">Median reviews LTM</th><th class="num">Future unavailable share</th></tr></thead><tbody>'+rows.map(r=>`<tr><td>${r.host_type}</td><td class="num">${fmt(r.listing_count)}</td><td class="num">${money(r.median_price)}</td><td class="num">${fmt(r.median_rating,2)}</td><td class="num">${fmt(r.median_occupancy_days)}</td><td class="num">${fmt(r.median_reviews_ltm)}</td><td class="num">${pct(r.median_unavailable_share_next_365d)}</td></tr>`).join('')+'</tbody>'}
renderHost();
function renderSeason(){const rows=D.seasonality,w=900,h=300,p={x:58,y:18,w:810,h:230},max=Math.max(...rows.map(r=>r.review_count),1),step=p.w/rows.length;let s=`<svg class="chart" role="img" aria-label="Monthly guest review counts for the trailing twelve complete months" viewBox="0 0 ${w} ${h}"><title>Monthly review counts</title>`;for(let i=0;i<=4;i++){let y=p.y+p.h-i*p.h/4;s+=`<line class="grid" x1="${p.x}" y1="${y}" x2="${p.x+p.w}" y2="${y}"/><text class="tick" x="${p.x-8}" y="${y+4}" text-anchor="end">${fmt(max*i/4)}</text>`}rows.forEach((r,i)=>{let bh=(r.review_count/max)*(p.h-8),x=p.x+i*step+step*.18,y=p.y+p.h-bh;s+=`<rect x="${x}" y="${y}" width="${step*.64}" height="${bh}" fill="#0d6c68" opacity=".78"/><text class="tick" x="${x+step*.32}" y="${p.y+p.h+17}" text-anchor="middle">${r.month.slice(5)}</text>`});s+=`<text class="tick" x="15" y="${p.y+p.h/2}" transform="rotate(-90 15 ${p.y+p.h/2})" text-anchor="middle">Guest reviews</text></svg>`;document.getElementById('season').innerHTML=s}
renderSeason();
const rooms=[...new Set(D.room_groups.map(r=>r.room_type))].sort();for(const id of ['scatter-room','filter-room']){const sel=document.getElementById(id);rooms.forEach(v=>sel.add(new Option(v,v)))}document.getElementById('scatter-room').value='Entire home/apt';
function scatter(){let room=document.getElementById('scatter-room').value,min=Number(document.getElementById('scatter-min').value)||1;let rows=D.room_groups.filter(r=>r.listing_count>=min&&(room==='All'||r.room_type===room)&&r.median_price!=null&&r.median_occupancy_days!=null);if(!rows.length){document.getElementById('scatter').innerHTML='<p class="empty">No groups match these filters.</p>';return}let x0=Math.min(...rows.map(r=>r.median_price)),x1=Math.max(...rows.map(r=>r.median_price)),y0=Math.min(...rows.map(r=>r.median_occupancy_days)),y1=Math.max(...rows.map(r=>r.median_occupancy_days));x0=Math.floor(x0/500)*500;x1=Math.ceil(x1/500)*500;if(x1===x0)x1=x0+1;y0=Math.floor(y0/10)*10;y1=Math.ceil(y1/10)*10;if(y1===y0)y1=y0+1;const xt=Array.from({length:5},(_,i)=>x0+(x1-x0)*i/4),yt=Array.from({length:5},(_,i)=>y0+(y1-y0)*i/4);let a=axisSvg({title:'Neighborhood median price versus demand',xmin:x0,xmax:x1,ymin:y0,ymax:y1,xticks:xt,yticks:yt,xlabel:'Median nightly price (THB)',ylabel:'Estimated occupancy (nights)',plot:{x:74,y:25,w:780,h:405}});let s=a.s;const p=a.plot;const xm=(x)=>p.x+(x-x0)/(x1-x0)*p.w,ym=(y)=>p.y+p.h-(y-y0)/(y1-y0)*p.h;const baseline=room==='All'?O:(O.room_type_baselines[room]||O);let mp=baseline.median_nightly_price_thb,mo=baseline.median_estimated_occupancy_days;s+=`<line x1="${xm(mp)}" y1="${p.y}" x2="${xm(mp)}" y2="${p.y+p.h}" stroke="#c59b4b" stroke-dasharray="5 5"/><line x1="${p.x}" y1="${ym(mo)}" x2="${p.x+p.w}" y2="${ym(mo)}" stroke="#c59b4b" stroke-dasharray="5 5"/>`;for(const r of rows){let rad=3+Math.sqrt(r.listing_count)/5;s+=`<circle class="bubble" cx="${xm(r.median_price)}" cy="${ym(r.median_occupancy_days)}" r="${rad.toFixed(1)}" data-neighborhood="${r.neighborhood}" data-room="${r.room_type}" data-listings="${r.listing_count}" data-price="${r.median_price}" data-occ="${r.median_occupancy_days}"/>`}s+='</svg>';document.getElementById('scatter').innerHTML=s;document.querySelectorAll('#scatter circle[data-neighborhood]').forEach(c=>{c.addEventListener('mousemove',e=>{const t=document.getElementById('tip');t.style.display='block';t.style.left=(e.clientX+12)+'px';t.style.top=(e.clientY+12)+'px';t.innerHTML=`${c.dataset.neighborhood} · ${c.dataset.room}<br>${fmt(c.dataset.listings)} listings · ${money(c.dataset.price)} · ${fmt(c.dataset.occ)} nights`});c.addEventListener('mouseleave',()=>document.getElementById('tip').style.display='none')})}
document.getElementById('scatter-room').addEventListener('change',scatter);document.getElementById('scatter-min').addEventListener('input',scatter);scatter();
function tableRows(el,rows,cols){el.innerHTML='<thead><tr>'+cols.map(c=>`<th class="${c.num?'num':''}">${c.label}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>`<td class="${c.num?'num':''}">${c.render?c.render(r[c.key]):htmlText(r[c.key])}</td>`).join('')+'</tr>').join('')+'</tbody>'}
function htmlText(v){return v==null?'—':String(v).replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]))}
const low=D.neighborhoods.filter(r=>r.listing_count>=O.minimum_neighborhood_sample_for_supply_flag&&r.median_occupancy_days>O.median_estimated_occupancy_days&&r.listing_count<=O.median_neighborhood_supply_cutoff).sort((a,b)=>b.median_occupancy_days-a.median_occupancy_days||a.listing_count-b.listing_count);
tableRows(document.getElementById('supply-table'),low,[{key:'neighborhood',label:'Neighborhood'},{key:'listing_count',label:'Active listings',num:true,render:fmt},{key:'median_price',label:'Median price',num:true,render:money},{key:'median_occupancy_days',label:'Estimated nights',num:true,render:fmt},{key:'median_reviews_ltm',label:'Reviews LTM',num:true,render:fmt}]);
const beds=[...new Set(D.pricing_groups.map(r=>r.bedrooms).filter(x=>x!=null))].sort((a,b)=>a-b);const bedSel=document.getElementById('filter-bed');beds.forEach(x=>bedSel.add(new Option(fmt(x),String(x))));
function pricing(){const room=document.getElementById('filter-room').value,bed=document.getElementById('filter-bed').value,search=document.getElementById('filter-neighborhood').value.toLowerCase(),flag=document.getElementById('filter-flag').value;const rows=D.pricing_groups.filter(r=>(room==='All'||r.room_type===room)&&(bed==='All'||String(r.bedrooms)===bed)&&r.neighborhood.toLowerCase().includes(search)).filter(r=>flag==='All'||r.opportunity_flag===flag).sort((a,b)=>flag==='Overpriced and weak'?b.overpriced_share-a.overpriced_share:b.underpriced_share-a.underpriced_share);document.getElementById('row-count').textContent=`${fmt(rows.length)} comparable groups`;tableRows(document.getElementById('pricing-table'),rows,[{key:'neighborhood',label:'Neighborhood'},{key:'room_type',label:'Room type'},{key:'bedrooms',label:'Bedrooms',num:true,render:fmt},{key:'comp_n',label:'Listings',num:true,render:fmt},{key:'median_price',label:'Median price',num:true,render:money},{key:'comp_median',label:'Peer median',num:true,render:money},{key:'median_price_index',label:'Median price index',num:true,render:v=>fmt(v,2)},{key:'underpriced_share',label:'Below 0.8',num:true,render:pct},{key:'overpriced_share',label:'Above 1.2',num:true,render:pct},{key:'median_occupancy_days',label:'Est. nights',num:true,render:fmt},{key:'median_reviews_ltm',label:'Reviews LTM',num:true,render:fmt},{key:'opportunity_flag',label:'Flag',render:v=>`<span class="flag ${v==='Overpriced and weak'?'warn':''}">${v}</span>`}])}
['filter-room','filter-bed','filter-flag'].forEach(id=>document.getElementById(id).addEventListener('change',pricing));document.getElementById('filter-neighborhood').addEventListener('input',pricing);pricing();
</script></body></html>'''
    OUT.joinpath("dashboard.html").write_text(template.replace("__DATA__", safe_data), encoding="utf-8")


def main():
    conn = db_connection()
    try:
        load_source(conn)
        sql = (ROOT / "sql" / "analysis.sql").read_text(encoding="utf-8")
        conn.executescript(sql)
        save_outputs(conn)
    finally:
        conn.close()
    print(f"Analysis complete. Results are in {OUT}")


if __name__ == "__main__":
    main()
