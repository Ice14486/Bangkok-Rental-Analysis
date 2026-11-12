# Where Are Bangkok Hosts Leaving Money on the Table?

This project compares Bangkok Airbnb asking prices with similar active listings and uses review-based occupancy, recent review counts, and future calendar availability as demand signals.

## Data and credit

The analysis uses the Inside Airbnb Bangkok snapshot dated 29 June 2026:

- [Detailed listings](https://data.insideairbnb.com/thailand/central-thailand/bangkok/2026-06-29/data/listings.csv.gz)
- [Detailed reviews](https://data.insideairbnb.com/thailand/central-thailand/bangkok/2026-06-29/visualisations/reviews.csv)
- [Inside Airbnb data dictionary](https://docs.google.com/spreadsheets/d/1iWCNJcSutYqpULSQHlNyGInUvHg2BoUGoNRIGa6Szc4/edit?usp=sharing)
- [Data assumptions](https://insideairbnb.com/data-assumptions/)
- [Data policies and CC BY 4.0 terms](https://insideairbnb.com/data-policies/)

Credit: **Inside Airbnb. (2026). Bangkok, Central Thailand, detailed listings and reviews, 29 June 2026 [Data set]. Housing Justice Data Lab.** Data is made available under the Creative Commons Attribution 4.0 International licence. The listing file carries `last_scraped` dates from 29 June through 2 July 2026; the source file is named for the 29 June scrape. The data dictionary says `price` is the daily price in local currency and that the `$` character is an export artifact, so prices here are reported in Thai baht (THB).

Inside Airbnb's occupancy estimate uses reviews to estimate bookings, adjusts for average stay and minimum nights, and caps occupancy at 70% of the year. It is not a count of observed bookings. Its calendar field also does not distinguish booked nights from host-blocked nights. See the linked [assumptions](https://insideairbnb.com/data-assumptions/) for those definitions. This work is an independent analysis; attribution does not imply endorsement.

## Rebuild

1. Put the two source files in `data/raw/` with these names: `listings.csv.gz` and `reviews.csv`.
2. Run `python3 scripts/analyze.py` with Python 3.11 or newer. The script uses only the standard library, SQLite, and the included SQL. Python registers a median aggregate/window function for SQLite.
3. Review `outputs/`. The raw source files and generated SQLite database are ignored by Git; they are not copied into the report outputs.

The detailed listings file has 90 columns. This version uses `neighbourhood_cleansed`, `room_type`, `bedrooms`, `price`, `estimated_occupancy_l365d`, `availability_365`, `number_of_reviews_ltm`, `review_scores_rating`, `calculated_host_listings_count`, `latitude`, and `longitude` (plus IDs and scrape dates needed for joins and audit). The occupancy field is present, so it is the primary occupancy measure. The future-availability proxy is `1 - availability_365 / 365` and is treated only as an additional cross-check.

## Cleaning and comparison rules

Filters are applied sequentially so each removal count is attributable to one step:

| Step | Removed | Remaining |
| --- | ---: | ---: |
| Source listings | — | 31,069 |
| Missing or unparseable price | 2,082 | 28,987 |
| Zero or negative price | 0 | 28,987 |
| Highest 0.5% of valid positive prices | 145 | 28,842 |
| No review in the last 12 months (`number_of_reviews_ltm < 1`) | 13,255 | 15,587 |

For the top-price rule, the script keeps `floor(99.5% × valid positive rows)` ordered by numeric price and listing ID, which removes exactly 0.5% (rounded up) in a reproducible way. The active sample is 50.2% of the source rows. Bedroom counts are not required for overall market summaries, but rows without a bedroom count are excluded from bedroom-matched pricing comparisons. Groups with fewer than 20 comparable listings are not shown.

`sql/analysis.sql` calculates each listing's peer median and `price_index` with SQL window functions, partitioned by cleaned neighborhood, room type, and bedroom count. A value below 0.8 is at least 20% below its peer median; above 1.2 is at least 20% above. Since a comparison group's own median index is near 1 by construction, group flags use the **share** of listings below 0.8 or above 1.2. A group is flagged when at least 25% of its eligible listings meet that price condition and its median estimated occupancy is above or below the active-sample city median. These thresholds are descriptive, not a statistical test.

For high-demand, lower-supply neighborhoods, the script requires at least 30 active listings, occupancy above the city median, and supply in the bottom quartile among neighborhoods with at least 30 active listings. Treat groups near the minimum cautiously.

## Demand and host comparisons

The cross-check compares neighborhood medians of `estimated_occupancy_l365d` and `number_of_reviews_ltm` for neighborhoods with at least 50 active listings. The script also reports the rank correlation between the occupancy estimate and next-year unavailability. The future availability field is not a past booking record.

Single-listing hosts have `calculated_host_listings_count = 1`; multi-listing hosts have a value greater than 1. This is a scale proxy, not proof of professional management. Host comparisons describe association within the review-active sample.

Monthly seasonality counts review dates for active listing IDs in the 12 full calendar months from July 2025 through June 2026. Reviews are not stay dates and may be posted after a stay.

## Outputs

- `outputs/dashboard.html`: three-page, self-contained market overview, neighborhood opportunity scatter, and pricing gap explorer.
- `outputs/memo.md`: one-page findings, recommendation, and caveats.
- CSVs and JSON in `outputs/`: cleaning audit, neighborhood/room and room/bedroom summaries, bedroom-matched pricing gaps, host comparison, demand cross-check, seasonality, and dashboard data.

## Main results

The active sample contains 15,587 listings. Median nightly price is THB 1,574.63, median estimated occupancy is 66 nights, and median recent review count is 5. Occupancy and recent-review neighborhood rankings disagree: among 33 neighborhoods with at least 50 active listings, Spearman rank correlation is 0.22 and only 3 of the top 10 neighborhoods overlap. The model's occupancy is review-based, so this is not an independent validation; model adjustments and the use of neighborhood medians also affect the comparison. Future calendar unavailability is more aligned with estimated occupancy (rank correlation 0.77), but booked and host-blocked dates are mixed together.

The dashboard and memo are for local analysis. If you share project results publicly, credit Inside Airbnb, identify the location and collection date, link the source, and follow its [data policies](https://insideairbnb.com/data-policies/).
