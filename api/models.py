from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, BigInteger
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    plan = Column(String(20), default="free")
    created_at = Column(DateTime, default=datetime.utcnow)

    products = relationship("Product", back_populates="user",
                            foreign_keys="Product.user_id",
                            cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(500), nullable=False)
    yahoo_gdid = Column(BigInteger, nullable=False)
    my_price = Column(Numeric(10, 2))
    alert_threshold_pct = Column(Numeric(5, 2), default=5.0)
    active = Column(Boolean, default=True)
    competitor_of = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="products", foreign_keys=[user_id])
    competitors = relationship("Product", foreign_keys="Product.competitor_of",
                               back_populates="parent_product", cascade="all, delete-orphan")
    parent_product = relationship("Product", foreign_keys=[competitor_of],
                                  back_populates="competitors", remote_side="Product.id")
    price_history = relationship("PriceHistory", back_populates="product", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="product", cascade="all, delete-orphan")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer)
    sold_count = Column(Integer)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="price_history")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    old_price = Column(Numeric(10, 2))
    new_price = Column(Numeric(10, 2))
    change_pct = Column(Numeric(5, 2))
    email_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="alerts")
