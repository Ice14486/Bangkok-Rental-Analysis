# Bangkok short-term rental pricing: one-page memo

**Snapshot:** Inside Airbnb Bangkok, 29 June 2026. Prices are nightly THB.

## Findings

1. **A small, lower-supply pocket stands out.** Chom Thong has 35 active listings, median estimated occupancy of 114 nights, and 5 reviews in the last 12 months, against city medians of 66 nights and 5 reviews. It falls in the bottom quartile for supply among neighborhoods with at least 30 active listings. A one-bedroom entire home/apt group has 22 comparables at a median THB 983, with 120 estimated occupied nights and 6 recent reviews. The comparison group is only just above the 20-listing minimum, so treat it as a lead to validate, not a dependable market benchmark.

2. **Bang Rak supports a higher asking-rate test for a one-bedroom entire place.** Its median price is THB 2,086 across 277 comparable listings, about 46% above the Bangkok median of THB 1,429 for one-bedroom entire homes/apartments. The group has 116 estimated occupied nights and 9 recent reviews at the median. About 30% of listings are priced at least 20% below their peer median, while 35% are at least 20% above it. Demand is strong by both available measures, but the wide price spread means quality and positioning matter; the data do not support pricing every unit at the top of the range.

3. **Some private-room segments look crowded and weak.** In Huai Khwang, one-bedroom private rooms have 121 comparable listings, median estimated occupancy of 40 nights, and 3 recent reviews. Around 41% are priced at least 20% above their peer median. Another 40% are at least 20% below it, so this is a dispersed segment rather than a group whose median is plainly overpriced. A room that lacks a clear quality or location advantage should avoid competing at the upper end.

**Host type:** Single-listing hosts have median price THB 1,655, rating 4.90, and estimated occupancy of 82 nights. Multi-listing hosts have THB 1,563, rating 4.86, and 60 estimated nights. Median recent reviews are 5 for both. In this active sample, larger host portfolios do not show stronger outcomes on these measures; the comparison is observational.

Review dates also show seasonality: monthly reviews peaked at 20,865 in January 2026 and fell to 9,985 in June. These are review dates, not the dates guests stayed.

## Recommendation

For a **one-bedroom entire home/apartment in Bang Rak**, test an initial nightly rate around **THB 1,900–2,300**, centered on the local comparable median of about THB 2,086. It is a premium-demand segment, with stronger occupancy and review medians than the citywide one-bedroom/entire-place comparison, but it also has 277 competitors. Use the range as a starting test, then adjust against actual booking pace and guest feedback.

## Cleaning and caveats

From 31,069 source rows, 2,082 had no parseable price, 0 had a zero or negative price, 145 were removed as the highest 0.5% of valid positive prices, and 13,255 had no review in the last 12 months. The analysis retains 15,587 listings (50.2%). “Active” means at least one review in the previous 12 months. Missing-bedroom rows remain in overall summaries but are excluded from bedroom-matched comparisons; peer groups under 20 are suppressed.

For opportunity flags, a neighborhood/room type group must have at least 20 comparable listings and at least 25% of them must fall below a 0.8 price index or above 1.2. “High” and “weak” demand mean above or below the city median occupancy estimate. This share rule avoids labeling a group by its own median index, which is near 1 by construction.

Estimated occupancy is a review-based model, not observed bookings. Review-count and occupancy rankings are weakly aligned: among 33 neighborhoods with 50 or more active listings, their rank correlation is 0.22 and their top-10 lists overlap in 3 neighborhoods. Future calendar unavailability can mean either booked or blocked by the host. Review seasonality is based on review dates, not stay dates. This is one snapshot, so the associations are not causal; smaller neighborhoods and groups near the 20-listing cutoff need local validation. Counts also depend on the active-listing rule above.

**Source:** Inside Airbnb, Bangkok detailed listings and reviews, 29 June 2026. [Listings file](https://data.insideairbnb.com/thailand/central-thailand/bangkok/2026-06-29/data/listings.csv.gz), [reviews file](https://data.insideairbnb.com/thailand/central-thailand/bangkok/2026-06-29/visualisations/reviews.csv), [data dictionary](https://docs.google.com/spreadsheets/d/1iWCNJcSutYqpULSQHlNyGInUvHg2BoUGoNRIGa6Szc4/edit?usp=sharing), [assumptions](https://insideairbnb.com/data-assumptions/), and [data policies](https://insideairbnb.com/data-policies/). CC BY 4.0. The data dictionary defines `price` in local currency and says the dollar sign is an export artifact.
