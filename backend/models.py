from sqlalchemy import Integer, Text, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid
from datetime import datetime
from typing import Optional

from database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    max_discount_pct: Mapped[int] = mapped_column(Integer, default=0)


class Mandate(Base):
    __tablename__ = "mandates"

    mandate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    buyer_agent_id: Mapped[Optional[str]] = mapped_column(Text)
    merchant_id: Mapped[Optional[str]] = mapped_column(Text)

    product_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("products.id")
    )

    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    agreed_price: Mapped[Optional[int]] = mapped_column(Integer)

    currency: Mapped[str] = mapped_column(Text, default="INR")
    status: Mapped[str] = mapped_column(Text, default="pending")
    signature: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mandates.mandate_id")
    )

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class RazorpayTransaction(Base):
    __tablename__ = "razorpay_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    mandate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mandates.mandate_id")
    )

    razorpay_order_id: Mapped[Optional[str]] = mapped_column(Text)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)