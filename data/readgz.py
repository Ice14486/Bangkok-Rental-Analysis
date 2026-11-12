import csv
import gzip
from pathlib import Path

path = Path(__file__).resolve().parent / "raw" / "listings.csv.gz"

with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)
    print(f"Features: {len(reader.fieldnames)}")
    print(*reader.fieldnames, sep="\n")

    listing = next(reader)
    print("\nExample values:")
    for column in ["id", "neighbourhood_cleansed", "room_type", "bedrooms", "price"]:
        print(f"{column}: {listing[column]}")
