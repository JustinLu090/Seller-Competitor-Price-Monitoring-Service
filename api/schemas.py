from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProductCreate(BaseModel):
    yahoo_url: str
    my_price: float | None = None
    alert_threshold_pct: float = 5.0


class CompetitorOut(BaseModel):
    id: int
    name: str
    yahoo_gdid: int
    latest_price: float | None = None
    last_scraped: datetime | None = None
    history_count: int = 0

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: int
    name: str
    yahoo_gdid: int
    my_price: float | None
    alert_threshold_pct: float
    active: bool
    created_at: datetime
    latest_price: float | None = None
    last_scraped: datetime | None = None
    history_count: int = 0
    competitor_of: int | None = None
    competitors: list[CompetitorOut] = []

    model_config = {"from_attributes": True}


class PricePoint(BaseModel):
    price: float
    scraped_at: datetime

    model_config = {"from_attributes": True}


class AlertOut(BaseModel):
    id: int
    product_id: int
    old_price: float | None
    new_price: float | None
    change_pct: float | None
    email_sent: bool
    created_at: datetime

    model_config = {"from_attributes": True}
