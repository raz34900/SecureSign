import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models_db import ReferenceSignature


def add(db: Session, customer_id: str, image_path: str, embedding: np.ndarray) -> ReferenceSignature:
    ref = ReferenceSignature(customer_id=customer_id, image_path=image_path,
                             embedding=embedding.astype(np.float32).tobytes())
    db.add(ref)
    return ref


def embeddings_for(db: Session, customer_id: str) -> list[np.ndarray]:
    rows = db.execute(select(ReferenceSignature.embedding)
                      .where(ReferenceSignature.customer_id == customer_id)).scalars().all()
    return [np.frombuffer(b, dtype=np.float32) for b in rows]
