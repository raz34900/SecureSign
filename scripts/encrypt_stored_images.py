"""Move signature images off the filesystem and into the database, encrypted.

Rows enrolled before the move point at a plain PNG beside the database. Anyone holding a
copy of both - a stray backup, a dump, a file-read bug - can put a name against a
signature, which is the whole reason the national ID next to it was encrypted. This reads
each of those files, encrypts it under the customer's key and writes it onto the row.

    python scripts/encrypt_stored_images.py --dry-run
    python scripts/encrypt_stored_images.py
    python scripts/encrypt_stored_images.py --delete-files

The two steps are deliberately separate: check that the application still shows the
images, and only then remove the plaintext. A backfill that deletes its own source before
anyone has looked is not recoverable.

--delete-files does not trust the paths on the rows, because a completed move has already
cleared them. It walks the legacy directories and deletes a file only when some row's
ciphertext decrypts to exactly those bytes - so a file is removed because the encrypted
copy has been proven readable, not because a column says it should be.
"""
import argparse
import hashlib
import os
import sys

from sqlalchemy import select

from backend.app import models_db  # noqa: F401
from backend.app.config import get_settings
from backend.app.db import make_engine, make_session_factory
from backend.app.models_db import ReferenceSignature, Verification
from backend.app.repositories import customer_keys
from backend.app.security import envelope

# Where images lived before they moved into the database. Nothing writes here any more.
LEGACY_DIRS = ("data/enrolment_samples", "data/verification_queries")


def _read(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _decrypted_digests(db) -> set[str]:
    """Every image the database can actually produce, by content.

    Content rather than path, because a row that has been migrated no longer remembers
    where its file was. A file whose digest is in here is provably redundant.
    """
    digests = set()
    keys: dict[str, bytes | None] = {}

    def dek_for(customer_id: str) -> bytes | None:
        if customer_id not in keys:
            keys[customer_id] = customer_keys.existing_key_for(db, customer_id)
        return keys[customer_id]

    for ref in db.execute(select(ReferenceSignature)).scalars():
        dek = dek_for(ref.customer_id)
        if not ref.image_encrypted or dek is None:
            continue
        try:
            raw = envelope.decrypt_image(ref.image_encrypted, dek, aad=ref.id.encode())
        except Exception:
            continue
        digests.add(hashlib.sha256(raw).hexdigest())

    for row in db.execute(select(Verification)).scalars():
        dek = dek_for(row.customer_id)
        if not row.query_image_encrypted or dek is None:
            continue
        try:
            raw = envelope.decrypt_image(row.query_image_encrypted, dek, aad=row.id.encode())
        except Exception:
            continue
        digests.add(hashlib.sha256(raw).hexdigest())

    return digests


def _delete_redundant_files(db, dry_run: bool) -> int:
    digests = _decrypted_digests(db)
    print(f"{len(digests)} distinct image(s) readable from the database\n")

    deleted = kept = 0
    for directory in LEGACY_DIRS:
        for root, _, names in os.walk(directory):
            for name in names:
                if not name.endswith(".png"):
                    continue
                path = os.path.join(root, name)
                raw = _read(path)
                if raw is None:
                    continue
                if hashlib.sha256(raw).hexdigest() not in digests:
                    print(f"  KEEPING  {path}  (no encrypted copy decrypts to this)")
                    kept += 1
                    continue
                if not dry_run:
                    os.remove(path)
                deleted += 1

    verb = "would delete" if dry_run else "deleted"
    print(f"\n{verb} {deleted} redundant plaintext file(s), kept {kept}")
    if kept:
        print("A kept file has no encrypted counterpart. Check it before removing it by "
              "hand - it may belong to a row whose key was destroyed, or to no row at all.")
    return kept


def _move_into_database(db, dry_run: bool) -> None:
    moved = skipped = missing = 0

    references = db.execute(select(ReferenceSignature)).scalars().all()
    verifications = db.execute(select(Verification).where(
        Verification.query_image_path.is_not(None))).scalars().all()
    print(f"{len(references)} reference(s), {len(verifications)} stored query image(s)\n")

    for ref in references:
        if ref.image_encrypted:
            skipped += 1
            continue
        raw = _read(ref.image_path)
        if raw is None:
            print(f"  reference {ref.id[:8]}  MISSING FILE  {ref.image_path}")
            missing += 1
            continue
        dek = customer_keys.key_for(db, ref.customer_id)
        blob = envelope.encrypt_image(raw, dek, aad=ref.id.encode())
        # Read it back before anything is considered moved. An encrypt that cannot be
        # reversed is worse than the plaintext it replaced.
        assert envelope.decrypt_image(blob, dek, aad=ref.id.encode()) == raw
        if not dry_run:
            ref.image_encrypted = blob
            ref.image_path = ""
        moved += 1
        print(f"  reference {ref.id[:8]}  {len(raw)} bytes")

    for row in verifications:
        if row.query_image_encrypted:
            skipped += 1
            continue
        raw = _read(row.query_image_path)
        if raw is None:
            print(f"  verification {row.id[:8]}  MISSING FILE  {row.query_image_path}")
            missing += 1
            continue
        dek = customer_keys.key_for(db, row.customer_id)
        blob = envelope.encrypt_image(raw, dek, aad=row.id.encode())
        assert envelope.decrypt_image(blob, dek, aad=row.id.encode()) == raw
        if not dry_run:
            row.query_image_encrypted = blob
            row.query_image_path = None
        moved += 1
        print(f"  verification {row.id[:8]}  {len(raw)} bytes")

    verb = "would move" if dry_run else "moved"
    print(f"\n{verb} {moved}, already encrypted {skipped}, missing file {missing}")
    if moved and not dry_run:
        print("The plaintext files are still on disk. Check the application shows the "
              "images, then run again with --delete-files.")
    if missing:
        print("A row whose file is gone keeps its verdict and loses only the picture.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen without writing or deleting")
    parser.add_argument("--delete-files", action="store_true",
                        help="remove plaintext files whose encrypted copy reads back intact")
    args = parser.parse_args()

    settings = get_settings()  # fails loudly here if the keys are absent, not mid-loop
    factory = make_session_factory(make_engine(settings.database_url))

    with factory() as db:
        if args.delete_files:
            kept = _delete_redundant_files(db, args.dry_run)
        else:
            _move_into_database(db, args.dry_run)
            kept = 0
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
