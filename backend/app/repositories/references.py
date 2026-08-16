"""Reference signatures. Ownership is per-org: an org manages only the references
it enrolled, but verification always compares against every org's references."""
import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models_db import ReferenceSignature

EMBEDDING_DIM = 128
EMBEDDING_BYTES = EMBEDDING_DIM * 4


def decode_embedding(blob: bytes | None) -> np.ndarray | None:
    """None for a row that is not a usable vector; callers skip it rather than crashing."""
    if not blob or len(blob) != EMBEDDING_BYTES:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def add(db: Session, customer_id: str, org_id: str, image_path: str,
        embedding: np.ndarray) -> ReferenceSignature:
    ref = ReferenceSignature(customer_id=customer_id, org_id=org_id, image_path=image_path,
                             embedding=embedding.astype(np.float32).tobytes())
    db.add(ref)
    return ref


def all_for(db: Session, customer_id: str) -> list[ReferenceSignature]:
    """Every org's references - the comparison set for verification."""
    return list(db.execute(select(ReferenceSignature)
                           .where(ReferenceSignature.customer_id == customer_id)).scalars())


def embeddings_for(db: Session, customer_id: str) -> list[np.ndarray]:
    rows = db.execute(select(ReferenceSignature.embedding)
                      .where(ReferenceSignature.customer_id == customer_id)).scalars().all()
    decoded = (decode_embedding(blob) for blob in rows)
    return [vector for vector in decoded if vector is not None]


def own_references(db: Session, customer_id: str, org_id: str) -> list[ReferenceSignature]:
    return list(db.execute(select(ReferenceSignature)
                           .where(ReferenceSignature.customer_id == customer_id,
                                  ReferenceSignature.org_id == org_id)).scalars())


def own_count(db: Session, customer_id: str, org_id: str) -> int:
    return db.execute(select(func.count()).select_from(ReferenceSignature)
                      .where(ReferenceSignature.customer_id == customer_id,
                             ReferenceSignature.org_id == org_id)).scalar_one()


def total_count(db: Session, customer_id: str) -> int:
    """References held for this customer across every organisation."""
    return int(db.execute(
        select(func.count()).select_from(ReferenceSignature)
        .where(ReferenceSignature.customer_id == customer_id)).scalar_one())
