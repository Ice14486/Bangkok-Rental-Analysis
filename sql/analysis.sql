-- Runs after the Python loader has created listings_source and registered
-- parse_price(), number_or_null(), and median(). The median window function
-- is Python's SQLite window aggregate, so this works with the system SQLite.

DROP TABLE IF EXISTS listings_typed;
CREATE TABLE listings_typed AS
SELECT
    listing_id,
    host_id,
    NULLIF(TRIM(neighborhood), '') AS neighborhood,
    NULLIF(TRIM(room_type), '') AS room_type,
    number_or_null(bedrooms_raw) AS bedrooms,
    parse_price(price_raw) AS price,
    number_or_null(estimated_occupancy_raw) AS estimated_occupancy_days,
    number_or_null(availability_365_raw) AS availability_365,
    number_or_null(reviews_ltm_raw) AS reviews_ltm,
    number_or_null(rating_raw) AS rating,
    number_or_null(host_listing_count_raw) AS host_listing_count,
    number_or_null(latitude_raw) AS latitude,
    number_or_null(longitude_raw) AS longitude,
    last_review,
    last_scraped
FROM listings_source;

DROP TABLE IF EXISTS listings_price_positive;
CREATE TABLE listings_price_positive AS
SELECT *
FROM listings_typed
WHERE price IS NOT NULL AND price > 0;

DROP TABLE IF EXISTS listings_price_ranked;
CREATE TABLE listings_price_ranked AS
SELECT
    *,
    ROW_NUMBER() OVER (ORDER BY price, listing_id) AS price_rank,
    COUNT(*) OVER () AS price_population
FROM listings_price_positive;

-- Keep floor(99.5% of valid positive prices), which removes the highest
-- ceil(0.5%) of rows. listing_id makes ties deterministic.
DROP TABLE IF EXISTS listings_clean;
CREATE TABLE listings_clean AS
SELECT *
FROM listings_price_ranked
WHERE price_rank <= CAST(price_population * 0.995 AS INTEGER);

DROP TABLE IF EXISTS listings_active;
CREATE TABLE listings_active AS
SELECT
    *,
    CASE WHEN availability_365 IS NOT NULL
         THEN 1.0 - availability_365 / 365.0 END AS unavailable_share_next_365d
FROM listings_clean
WHERE reviews_ltm >= 1;

-- Listing level price comparison. Missing bedroom counts are excluded so
-- each comparison is between listings with a known, matching bedroom count.
DROP TABLE IF EXISTS listing_comps;
CREATE TABLE listing_comps AS
WITH comp AS (
    SELECT
        *,
        MEDIAN(price) OVER (
            PARTITION BY neighborhood, room_type, bedrooms
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS comp_median,
        COUNT(*) OVER (
            PARTITION BY neighborhood, room_type, bedrooms
        ) AS comp_n
    FROM listings_active
    WHERE neighborhood IS NOT NULL
      AND room_type IS NOT NULL
      AND bedrooms IS NOT NULL
)
SELECT *, price / comp_median AS price_index
FROM comp;

DROP TABLE IF EXISTS pricing_gap_groups;
CREATE TABLE pricing_gap_groups AS
SELECT
    neighborhood,
    room_type,
    bedrooms,
    COUNT(*) AS comp_n,
    SUM(CASE WHEN price_index < 0.8 THEN 1 ELSE 0 END) AS underpriced_count,
    SUM(CASE WHEN price_index < 0.8 THEN 1.0 ELSE 0.0 END) / COUNT(*) AS underpriced_share,
    SUM(CASE WHEN price_index > 1.2 THEN 1 ELSE 0 END) AS overpriced_count,
    SUM(CASE WHEN price_index > 1.2 THEN 1.0 ELSE 0.0 END) / COUNT(*) AS overpriced_share,
    MEDIAN(price) AS median_price,
    MEDIAN(comp_median) AS comp_median,
    MEDIAN(price_index) AS median_price_index,
    MEDIAN(estimated_occupancy_days) AS median_occupancy_days,
    MEDIAN(reviews_ltm) AS median_reviews_ltm,
    MEDIAN(unavailable_share_next_365d) AS median_unavailable_share_next_365d,
    MEDIAN(rating) AS median_rating
FROM listing_comps
WHERE comp_n >= 20
GROUP BY neighborhood, room_type, bedrooms;

DROP TABLE IF EXISTS neighborhood_room_summary;
CREATE TABLE neighborhood_room_summary AS
WITH base AS (
    SELECT
        neighborhood,
        room_type,
        COUNT(*) AS listing_count,
        MEDIAN(price) AS median_price,
        MEDIAN(estimated_occupancy_days) AS median_occupancy_days,
        MEDIAN(reviews_ltm) AS median_reviews_ltm,
        MEDIAN(unavailable_share_next_365d) AS median_unavailable_share_next_365d,
        MEDIAN(rating) AS median_rating
    FROM listings_active
    WHERE neighborhood IS NOT NULL AND room_type IS NOT NULL
    GROUP BY neighborhood, room_type
), gap AS (
    SELECT
        neighborhood,
        room_type,
        COUNT(*) AS gap_listing_count,
        MEDIAN(price_index) AS median_price_index,
        SUM(CASE WHEN price_index < 0.8 THEN 1 ELSE 0 END) AS underpriced_count,
        SUM(CASE WHEN price_index < 0.8 THEN 1.0 ELSE 0.0 END) / COUNT(*) AS underpriced_share,
        SUM(CASE WHEN price_index > 1.2 THEN 1 ELSE 0 END) AS overpriced_count,
        SUM(CASE WHEN price_index > 1.2 THEN 1.0 ELSE 0.0 END) / COUNT(*) AS overpriced_share
    FROM listing_comps
    WHERE comp_n >= 20
    GROUP BY neighborhood, room_type
)
SELECT
    base.*,
    COALESCE(gap.gap_listing_count, 0) AS gap_listing_count,
    gap.median_price_index,
    COALESCE(gap.underpriced_count, 0) AS underpriced_count,
    gap.underpriced_share,
    COALESCE(gap.overpriced_count, 0) AS overpriced_count,
    gap.overpriced_share
FROM base
LEFT JOIN gap USING (neighborhood, room_type);

DROP TABLE IF EXISTS neighborhood_summary;
CREATE TABLE neighborhood_summary AS
SELECT
    neighborhood,
    COUNT(*) AS listing_count,
    MEDIAN(price) AS median_price,
    MEDIAN(estimated_occupancy_days) AS median_occupancy_days,
    MEDIAN(reviews_ltm) AS median_reviews_ltm,
    MEDIAN(unavailable_share_next_365d) AS median_unavailable_share_next_365d
FROM listings_active
WHERE neighborhood IS NOT NULL
GROUP BY neighborhood;

DROP TABLE IF EXISTS host_type_summary;
CREATE TABLE host_type_summary AS
SELECT
    CASE WHEN host_listing_count = 1 THEN 'Single-listing host'
         WHEN host_listing_count > 1 THEN 'Multi-listing host'
         ELSE 'Unknown host count' END AS host_type,
    COUNT(*) AS listing_count,
    MEDIAN(price) AS median_price,
    MEDIAN(rating) AS median_rating,
    COUNT(rating) AS rated_listing_count,
    MEDIAN(estimated_occupancy_days) AS median_occupancy_days,
    MEDIAN(reviews_ltm) AS median_reviews_ltm,
    MEDIAN(unavailable_share_next_365d) AS median_unavailable_share_next_365d
FROM listings_active
GROUP BY host_type;
