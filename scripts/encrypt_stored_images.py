"""Move signature images off the filesystem and into the database, encrypted.

Rows enrolled before the move point at a plain PNG beside the database. Anyone holding a
copy of both — a stray backup, a dump, a file-read bug — can put a name against a
signature, which is the whole reason the national ID next to it was encrypted. This reads
each of those files, encrypts it under the customer's key and writes it onto the row.

    python scripts/encrypt_stored_images.py --dry-run
    python scripts/encrypt_stored_images.py
    python scripts/encrypt_stored_images.py --delete-files

The plaintext files are left alone unless --delete-files is given, and that flag only
touches a file whose contents are already encrypted on the row and read back byte for
byte. Run it once, check the application, then run it again with the flag: a backfill
that deletes its own source before anyone has looked is not recoverable.

Nothing here is destructive to a row. A file that cannot be read is reported and skipped.
"""
import argparse
import os
import sys

from sqlalchemy import select

from backend.app import models_db  # noqa: F401
from backend.app.config import get_settings
from backend.app.db import make_engine, make_session_factory
from backend.app.models_db import ReferenceSignature, Verification
from backend.app.repositories import customer_keys
from backend.app.security import envelope


def _read(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would move without writing")
    parser.add_argument("--delete-files", action="store_true",
                        help="remove a plaintext file once its ciphertext reads back intact")
    args = parser.parse_args()

    get_settings()  # fails loudly here if the keys are absent, rather than mid-loop
    factory = make_session_factory(make_engine(get_settings().database_url))

    moved = skipped = missing = 0
    removable: list[str] = []

    with factory() as db:
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
            if not args.dry_run:
                ref.image_encrypted = blob
                removable.append(ref.image_path)
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
            if not args.dry_run:
                row.query_image_encrypted = blob
                removable.append(row.query_image_path)
                row.query_image_path = None
            moved += 1
            print(f"  verification {row.id[:8]}  {len(raw)} bytes")

        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    if args.delete_files and not args.dry_run:
        for path in removable:
            try:
                os.remove(path)
            except OSError:
                pass

    verb = "would move" if args.dry_run else "moved"
    print(f"\n{verb} {moved}, already encrypted {skipped}, missing file {missing}")
    if moved and not args.delete_files and not args.dry_run:
        print("The plaintext files are still on disk. Check the application reads the "
              "images, then run again with --delete-files.")
    if missing:
        print("A row whose file is gone keeps its verdict and loses only the picture.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
