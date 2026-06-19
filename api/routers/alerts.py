from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Alert, Product, User
from routers.auth import get_current_user
from schemas import AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_product_ids = [
        p.id for p in db.query(Product.id).filter(Product.user_id == current_user.id).all()
    ]
    if not user_product_ids:
        return []

    return (
        db.query(Alert)
        .filter(Alert.product_id.in_(user_product_ids))
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
