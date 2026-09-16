from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.business_service import query_businesses

router = APIRouter(prefix="/api", tags=["map"])

# Rough bounding box for Belgium — anything outside is a suspect coordinate.
LON_RANGE = (2.0, 7.0)
LAT_RANGE = (49.0, 52.0)


def _valid_coords(lon, lat) -> bool:
    return (
        isinstance(lon, (int, float))
        and isinstance(lat, (int, float))
        and LON_RANGE[0] <= lon <= LON_RANGE[1]
        and LAT_RANGE[0] <= lat <= LAT_RANGE[1]
    )


@router.get("/map")
def map_features(
    query: str | None = None,
    sector: str | None = None,
    street: str | None = None,
    postcode: str | None = None,
    municipality: str | None = None,
    record_type: str | None = None,
    legal_status: str | None = None,
    google_status: str | None = None,
    review_required: bool | None = None,
    has_email: bool | None = None,
    has_phone: bool | None = None,
    has_website: bool | None = None,
    db: Session = Depends(get_db),
):
    """Normalized GeoJSON FeatureCollection for the frontend map. The frontend
    never needs to parse the original KBO GeoJSON."""
    result = query_businesses(db, {
        "query": query,
        "sector": sector,
        "street": street,
        "postcode": postcode,
        "municipality": municipality,
        "record_type": record_type,
        "legal_status": legal_status,
        "google_status": google_status,
        "review_required": review_required,
        "has_email": has_email,
        "has_phone": has_phone,
        "has_website": has_website,
        "limit": 500,  # cap per page; dataset is 1000, map uses two pages max
        "offset": 0,
    })

    # Pull every matching record (query_businesses caps limit at 500).
    items = list(result["results"])
    while len(items) < result["total"]:
        more = query_businesses(db, {
            "query": query, "sector": sector, "street": street, "postcode": postcode,
            "municipality": municipality, "record_type": record_type,
            "legal_status": legal_status, "google_status": google_status,
            "review_required": review_required, "has_email": has_email,
            "has_phone": has_phone, "has_website": has_website,
            "limit": 500, "offset": len(items),
        })
        if not more["results"]:
            break
        items.extend(more["results"])

    features = []
    skipped = 0
    for item in items:
        if not _valid_coords(item["longitude"], item["latitude"]):
            skipped += 1
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [item["longitude"], item["latitude"]],
            },
            "properties": {
                "id": item["id"],
                "display_name": item["display_name"],
                "business_number": item["business_number"],
                "record_type": item["record_type"],
                "address": item["address"],
                "confidence_score": item["confidence_score"],
                "confidence_level": item["confidence_level"],
                "review_required": item["review_required"],
                "google_status": item["google_status"],
                "has_email": item["has_email"],
                "has_phone": item["has_phone"],
                "has_website": item["has_website"],
                "sectors": item["sectors"],
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "total_matching": result["total"],
        "skipped_invalid_coordinates": skipped,
    }
