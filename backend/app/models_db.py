import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organisation(Base):
    __tablename__ = "organisations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(12), unique=True)  # BA11 — what you log in with
    name: Mapped[str] = mapped_column(String(120), unique=True)  # Bank A — display only
    type: Mapped[str] = mapped_column(String(20))  # financial | subscriber | operator
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "username"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    username: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # clerk | verifier | org_admin | engineer
    is_active: Mapped[bool] = mapped_column(default=True)
    # An administrator who sets someone's password knows it; the account is not private
    # until its owner has replaced it, so nothing else works until they do.
    must_change_password: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("national_id_index"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    national_id_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    national_id_index: Mapped[str] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(120))
    enrolled_by_org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | deleted
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    granted_at: Mapped[datetime] = mapped_column(default=_now)
    method: Mapped[str] = mapped_column(String(20))  # signed_form | in_person


class ReferenceSignature(Base):
    __tablename__ = "reference_signatures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))  # owning org
    image_path: Mapped[str] = mapped_column(String(255))
    embedding: Mapped[bytes] = mapped_column(LargeBinary)  # 128 float32 = 512 bytes
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Verification(Base):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    requesting_org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    requesting_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(10))  # VALID | FRAUD
    distance: Mapped[float] = mapped_column(Float)
    threshold_used: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    at: Mapped[datetime] = mapped_column(default=_now)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(10))  # allowed | denied
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON text


class ModelFeedback(Base):
    __tablename__ = "model_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    verification_id: Mapped[str | None] = mapped_column(ForeignKey("verifications.id"), nullable=True)
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(20), default="engineer")  # engineer | institution
    status: Mapped[str] = mapped_column(String(10), default="pending")   # pending | accepted | rejected
    claimed_label: Mapped[str] = mapped_column(String(10))               # genuine | forged
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
