from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.kbo_import import run_import

router = APIRouter(prefix="/api", tags=["admin"])


@router.post("/admin/import")
def admin_import(db: Session = Depends(get_db)):
    """Idempotent import of the supplied KBO snapshot (GeoJSON canonical,
    CSV as sanity check). Safe to run repeatedly."""
    return run_import(db)
