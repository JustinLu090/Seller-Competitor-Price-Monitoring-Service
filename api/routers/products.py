import logging
import os
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Alert, Product, PriceHistory, User
from routers.auth import get_current_user
from schemas import ProductCreate, ProductOut, CompetitorOut, PricePoint
from yahoo_spider import parse_yahoo_url, fetch_product, search_competitor_gdids, _extract_keyword

router = APIRouter(prefix="/products", tags=["products"])

GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD", "")


def _send_alert_email(to: str, product_name: str, competitor_name: str,
                      my_price: float, comp_price: float, change_pct: float):
    if not GMAIL_USER or not GMAIL_PASS:
        return
    try:
        msg = MIMEMultipart()
        msg["Subject"] = f"[競品降價警報] {competitor_name[:30]} 比你便宜 {change_pct:.1f}%"
        msg["From"] = GMAIL_USER
        msg["To"] = to
        body = (
            f"競品降價通知\n\n"
            f"您監控的商品：{product_name}\n"
            f"您的定價：NT${my_price:.0f}\n\n"
            f"競品：{competitor_name}\n"
            f"競品現價：NT${comp_price:.0f}\n"
            f"比您便宜：{change_pct:.1f}%\n\n"
            f"建議您考慮調整自己的定價策略。\n"
        )
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.send_message(msg)
    except Exception as exc:
        print(f"[email] send failed: {exc}")


def _enrich(products: list, db: Session) -> dict:
    """Return {product_id: {latest_price, last_scraped, history_count}} for a list of products."""
    ids = [p.id for p in products]
    if not ids:
        return {}

    stats = (
        db.query(
            PriceHistory.product_id,
            func.max(PriceHistory.scraped_at).label("last_scraped"),
            func.count(PriceHistory.id).label("history_count"),
        )
        .filter(PriceHistory.product_id.in_(ids))
        .group_by(PriceHistory.product_id)
        .all()
    )
    stat_map = {s.product_id: s for s in stats}

    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id.in_(ids))
        .order_by(PriceHistory.scraped_at.desc())
        .all()
    )
    seen: set[int] = set()
    latest_map: dict[int, float] = {}
    for row in rows:
        if row.product_id not in seen:
            latest_map[row.product_id] = float(row.price)
            seen.add(row.product_id)

    result: dict[int, dict] = {}
    for p in products:
        s = stat_map.get(p.id)
        result[p.id] = {
            "latest_price": latest_map.get(p.id),
            "last_scraped": s.last_scraped if s else None,
            "history_count": s.history_count if s else 0,
        }
    return result


def _discover_competitors(product: Product, alert_threshold_pct: float, db: Session) -> list[CompetitorOut]:
    """Search Yahoo for similar products and save them as competitors of the given parent."""
    keyword = _extract_keyword(product.name)
    logger.info("Discovering competitors for '%s' keyword='%s'", product.name, keyword)
    comp_gdids = search_competitor_gdids(keyword, exclude_gdid=int(product.yahoo_gdid), limit=5)
    found: list[CompetitorOut] = []
    for cgdid in comp_gdids:
        dup = db.query(Product).filter(
            Product.user_id == product.user_id,
            Product.yahoo_gdid == cgdid,
        ).first()
        if dup:
            continue
        cresult = fetch_product(cgdid, retries=1)
        if not cresult:
            continue
        try:
            sp = db.begin_nested()
            comp = Product(
                user_id=product.user_id,
                name=cresult["name"],
                yahoo_gdid=cgdid,
                my_price=None,
                alert_threshold_pct=alert_threshold_pct,
                competitor_of=product.id,
            )
            db.add(comp)
            db.flush()
            db.add(PriceHistory(
                product_id=comp.id,
                price=cresult["price"],
                stock=cresult.get("stock", 0),
                sold_count=0,
            ))
            sp.commit()
            found.append(CompetitorOut(
                id=comp.id,
                name=comp.name,
                yahoo_gdid=comp.yahoo_gdid,
                latest_price=cresult["price"],
                history_count=1,
            ))
        except Exception as exc:
            logger.warning("Skip competitor gdid=%s (%s)", cgdid, exc)
            sp.rollback()
    return found


@router.get("", response_model=list[ProductOut])
def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Parent products (the ones the user added)
    parents = (
        db.query(Product)
        .filter(
            Product.user_id == current_user.id,
            Product.active == True,
            Product.competitor_of == None,
        )
        .all()
    )

    # All competitors for this user's products
    parent_ids = [p.id for p in parents]
    competitors = (
        db.query(Product)
        .filter(
            Product.competitor_of.in_(parent_ids),
            Product.active == True,
        )
        .all()
    ) if parent_ids else []

    all_products = parents + competitors
    enrichment = _enrich(all_products, db)

    # Build competitor map
    comp_map: dict[int, list[CompetitorOut]] = {pid: [] for pid in parent_ids}
    for c in competitors:
        e = enrichment[c.id]
        comp_map[c.competitor_of].append(CompetitorOut(
            id=c.id,
            name=c.name,
            yahoo_gdid=c.yahoo_gdid,
            latest_price=e["latest_price"],
            last_scraped=e["last_scraped"],
            history_count=e["history_count"],
        ))

    result = []
    for p in parents:
        e = enrichment[p.id]
        out = ProductOut(
            id=p.id,
            name=p.name,
            yahoo_gdid=p.yahoo_gdid,
            my_price=float(p.my_price) if p.my_price else None,
            alert_threshold_pct=float(p.alert_threshold_pct),
            active=p.active,
            created_at=p.created_at,
            latest_price=e["latest_price"],
            last_scraped=e["last_scraped"],
            history_count=e["history_count"],
            competitor_of=None,
            competitors=comp_map.get(p.id, []),
        )
        result.append(out)
    return result


@router.post("", response_model=ProductOut, status_code=201)
def add_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    gdid = parse_yahoo_url(payload.yahoo_url)

    # Check for any existing row with this gdid (parent or competitor)
    existing = db.query(Product).filter(
        Product.user_id == current_user.id,
        Product.yahoo_gdid == gdid,
    ).first()

    if existing:
        if existing.active and existing.competitor_of is None:
            raise HTTPException(status_code=409, detail="Product already being monitored")
        # Promote competitor → parent, or reactivate
        existing.active = True
        existing.my_price = payload.my_price
        existing.alert_threshold_pct = payload.alert_threshold_pct
        existing.competitor_of = None
        db.commit()
        db.refresh(existing)
        return ProductOut(
            id=existing.id, name=existing.name, yahoo_gdid=existing.yahoo_gdid,
            my_price=float(existing.my_price) if existing.my_price else None,
            alert_threshold_pct=float(existing.alert_threshold_pct),
            active=existing.active, created_at=existing.created_at,
            competitors=[],
        )

    # Fetch name from Yahoo
    result = fetch_product(gdid, retries=1)
    name = result["name"] if result else f"商品 {gdid}"

    product = Product(
        user_id=current_user.id,
        name=name,
        yahoo_gdid=gdid,
        my_price=payload.my_price,
        alert_threshold_pct=payload.alert_threshold_pct,
        competitor_of=None,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    # Auto-discover competitors via search
    competitors_out = _discover_competitors(product, payload.alert_threshold_pct, db)
    db.commit()

    return ProductOut(
        id=product.id,
        name=product.name,
        yahoo_gdid=product.yahoo_gdid,
        my_price=float(product.my_price) if product.my_price else None,
        alert_threshold_pct=float(product.alert_threshold_pct),
        active=product.active,
        created_at=product.created_at,
        competitors=competitors_out,
    )


@router.delete("/{product_id}", status_code=204)
def remove_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == current_user.id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    # Soft-delete parent and all its competitors
    product.active = False
    for comp in db.query(Product).filter(Product.competitor_of == product_id).all():
        comp.active = False
    db.commit()


@router.get("/{product_id}/history", response_model=list[PricePoint])
def price_history(
    product_id: int,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == current_user.id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.scraped_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/scrape-all", status_code=200)
def scrape_all_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import random
    all_products = (
        db.query(Product)
        .filter(Product.user_id == current_user.id, Product.active == True)
        .all()
    )
    results = []
    for product in all_products:
        price = None
        source = "yahoo"
        try:
            r = fetch_product(int(product.yahoo_gdid))
            if r:
                price = r["price"]
        except Exception:
            pass

        if price is None:
            last = (
                db.query(PriceHistory)
                .filter(PriceHistory.product_id == product.id)
                .order_by(PriceHistory.scraped_at.desc())
                .first()
            )
            base = float(last.price) if last else None
            if base:
                price = round(base * (1 + random.uniform(-0.02, 0.02)), 0)
                source = "simulated"

        if price is not None:
            db.add(PriceHistory(product_id=product.id, price=price, stock=0, sold_count=0))
            results.append({"id": product.id, "name": product.name, "price": price, "source": source})

            # Check alert for competitor products against the parent's my_price
            if product.competitor_of:
                parent = db.query(Product).filter(Product.id == product.competitor_of).first()
                if parent and parent.my_price:
                    my_price = float(parent.my_price)
                    threshold = float(parent.alert_threshold_pct or 5.0)
                    if price < my_price:
                        diff_pct = (my_price - price) / my_price * 100
                        if diff_pct >= threshold:
                            alert = Alert(
                                product_id=product.id,
                                old_price=my_price,
                                new_price=price,
                                change_pct=round(diff_pct, 1),
                            )
                            db.add(alert)
                            db.flush()
                            # Get user email for notification
                            from models import User as UserModel
                            user = db.query(UserModel).filter(UserModel.id == current_user.id).first()
                            if user:
                                _send_alert_email(
                                    to=user.email,
                                    product_name=parent.name,
                                    competitor_name=product.name,
                                    my_price=my_price,
                                    comp_price=price,
                                    change_pct=round(diff_pct, 1),
                                )

    # Re-discover competitors for any parent that currently has none
    rediscovered = 0
    parents = [p for p in all_products if p.competitor_of is None]
    for parent in parents:
        active_comp_count = db.query(Product).filter(
            Product.competitor_of == parent.id,
            Product.active == True,
        ).count()
        if active_comp_count == 0:
            new_comps = _discover_competitors(parent, float(parent.alert_threshold_pct), db)
            db.commit()
            rediscovered += len(new_comps)
            logger.info("Re-discovered %d competitors for product id=%s", len(new_comps), parent.id)

    db.commit()
    return {"scraped": len(results), "products": results, "rediscovered_competitors": rediscovered}


@router.post("/{product_id}/scrape", status_code=200)
def scrape_now(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import random
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == current_user.id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    price = None
    source = "yahoo"
    try:
        r = fetch_product(int(product.yahoo_gdid))
        if r:
            price = r["price"]
    except Exception:
        pass

    if price is None:
        last = (
            db.query(PriceHistory)
            .filter(PriceHistory.product_id == product.id)
            .order_by(PriceHistory.scraped_at.desc())
            .first()
        )
        base = float(last.price) if last else (float(product.my_price) if product.my_price else None)
        if base is None:
            raise HTTPException(status_code=422, detail="無法取得價格，請先執行「Demo 降價」載入初始資料。")
        price = round(base * (1 + random.uniform(-0.02, 0.02)), 0)
        source = "simulated"

    db.add(PriceHistory(product_id=product.id, price=price, stock=0, sold_count=0))
    db.commit()
    return {"price": price, "source": source}


@router.post("/{product_id}/seed", status_code=200)
def seed_demo(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Insert 7 days of demo price history for this product and trigger an alert."""
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.user_id == current_user.id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    now = datetime.utcnow()
    # Use latest known price or my_price or 500 as base
    last = (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.scraped_at.desc())
        .first()
    )
    base_price = float(last.price) if last else float(product.my_price or 500)

    points = []
    for day in range(7):
        for slot in range(4):
            ts = now - timedelta(days=6 - day, hours=(3 - slot) * 6)
            if day < 5:
                price = base_price * (1 - day * 0.015 - slot * 0.002)
            elif day == 5:
                price = base_price * (0.925 - slot * 0.002)
            else:
                price = base_price * (0.919 - slot * 0.002) if slot < 3 else base_price * 0.80
            points.append(PriceHistory(
                product_id=product.id,
                price=round(price, 0),
                stock=50,
                sold_count=100 + day * 10 + slot,
                scraped_at=ts,
            ))

    db.add_all(points)
    db.flush()

    old_price = round(base_price * 0.919, 0)
    new_price = round(base_price * 0.80, 0)
    drop_pct = round((old_price - new_price) / old_price * 100, 1)

    alert = Alert(
        product_id=product.id,
        old_price=old_price,
        new_price=new_price,
        change_pct=drop_pct,
        created_at=now,
    )
    db.add(alert)
    db.commit()

    # Send email if this competitor is cheaper than the parent's my_price
    if product.competitor_of:
        parent = db.query(Product).filter(Product.id == product.competitor_of).first()
        if parent and parent.my_price:
            my_p = float(parent.my_price)
            if new_price < my_p:
                diff = round((my_p - new_price) / my_p * 100, 1)
                threshold = float(parent.alert_threshold_pct or 5.0)
                if diff >= threshold:
                    from models import User as UserModel
                    user = db.query(UserModel).filter(UserModel.id == current_user.id).first()
                    if user:
                        _send_alert_email(
                            to=user.email,
                            product_name=parent.name,
                            competitor_name=product.name,
                            my_price=my_p,
                            comp_price=new_price,
                            change_pct=diff,
                        )
    return {"inserted": len(points), "drop_pct": drop_pct}
