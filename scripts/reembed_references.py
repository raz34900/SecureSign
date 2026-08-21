"""Recompute every stored reference embedding from the stored image.

The embedding a reference carries was produced by whatever preparation was in force the
day it was enrolled. When that preparation changes — a new cleanup stage, a fixed
extraction bug — stored references and fresh queries stop being comparable, and every
customer enrolled before the change starts failing verification for no reason they did.

This re-runs the current preparation over the stored crop and writes the new vector. The
image is the record; the embedding is derived, and derived data can be rebuilt — which is
why the crop is archived at the resolution it was cut at rather than at the 224x224 the
model reads.

A customer whose key has been destroyed has no readable image, so there is nothing to
rebuild from and the row is reported rather than guessed at.

    python scripts/reembed_references.py --dry-run
    python scripts/reembed_references.py

Nothing else changes: the same row, the same image, the same customer.
"""
import argparse
import io
import sys

import numpy as np
from PIL import Image
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.db import make_engine, make_session_factory
from backend.app import models_db  # noqa: F401
from backend.app.models_db import ReferenceSignature
from backend.app.repositories import customer_keys
from backend.app.services.verification import reference_image_bytes
from signature_core.cleanup import isolate_signature_ink, pad_for_rotation
from signature_core.embed import Embedder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args()

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    embedder = Embedder.load(settings.model_path)

    rebuilt = unchanged = missing = 0
    with factory() as db:
        rows = db.execute(select(ReferenceSignature)).scalars().all()
        print(f"{len(rows)} reference(s) on file\n")

        keys: dict[str, bytes | None] = {}
        for ref in rows:
            if ref.customer_id not in keys:
                keys[ref.customer_id] = customer_keys.existing_key_for(db, ref.customer_id)
            raw = reference_image_bytes(ref, keys[ref.customer_id])
            if raw is None:
                print(f"  {ref.id[:8]}  UNREADABLE IMAGE  customer {ref.customer_id[:8]}")
                missing += 1
                continue
            image = Image.open(io.BytesIO(raw)).convert("L")

            # The same two steps enrolment and verification run.
            vector = embedder.embed(pad_for_rotation(isolate_signature_ink(image)))
            before = np.frombuffer(ref.embedding, dtype=np.float32)
            moved = float(np.linalg.norm(vector - before)) if len(before) == 128 else float("inf")

            if moved < 1e-6:
                unchanged += 1
                continue

            print(f"  {ref.id[:8]}  moved {moved:.4f}")
            if not args.dry_run:
                ref.embedding = vector.astype(np.float32).tobytes()
            rebuilt += 1

        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    verb = "would rebuild" if args.dry_run else "rebuilt"
    print(f"\n{verb} {rebuilt}, unchanged {unchanged}, missing image {missing}")
    if missing:
        print("A reference whose image cannot be read keeps its old vector and is now "
              "inconsistent with the rest. Delete it, or re-enrol that customer. If the "
              "customer's key was destroyed, that is erasure working as intended.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
