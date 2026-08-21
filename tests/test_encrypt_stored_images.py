"""The backfill's delete pass, which is the only code in this project that removes a
signature image from disk.

It deletes by content, not by path, and the reason is a bug this script already had: the
move clears `image_path`, so a later run with --delete-files had no list of files to
remove and silently did nothing. Matching a file against what the database can actually
decrypt removes the ordering problem entirely — a file goes only when the encrypted copy
has been proven readable.
"""
import hashlib

from sqlalchemy import select

from conftest import login
from scripts import encrypt_stored_images as backfill
from test_enrolment import do_full_enrolment


def enrolled(client, session_factory, national_id: str = "123457000"):
    login(client, "BA11", "clerk1")
    customer_id = do_full_enrolment(client, national_id)
    from backend.app.models_db import ReferenceSignature
    from backend.app.repositories import customer_keys
    from backend.app.services.verification import reference_image_bytes

    with session_factory() as db:
        ref = db.execute(select(ReferenceSignature).where(
            ReferenceSignature.customer_id == customer_id)).scalars().first()
        raw = reference_image_bytes(ref, customer_keys.existing_key_for(db, customer_id))
    return customer_id, raw


def test_a_file_the_database_can_reproduce_is_deleted(client, seeded, session_factory,
                                                      tmp_path, monkeypatch):
    _, raw = enrolled(client, session_factory)
    legacy = tmp_path / "samples"
    legacy.mkdir()
    redundant = legacy / "copy.png"
    redundant.write_bytes(raw)
    monkeypatch.setattr(backfill, "LEGACY_DIRS", (str(legacy),))

    with session_factory() as db:
        assert backfill._delete_redundant_files(db, dry_run=False) == 0
    assert not redundant.exists()


def test_a_file_nothing_can_reproduce_is_kept(client, seeded, session_factory,
                                              tmp_path, monkeypatch):
    """The safety property. An unmatched file may belong to a row whose key was
    destroyed, or to no row at all — either way it is not this script's to delete."""
    enrolled(client, session_factory, "123457001")
    legacy = tmp_path / "samples"
    legacy.mkdir()
    stranger = legacy / "stranger.png"
    stranger.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not from this database")
    monkeypatch.setattr(backfill, "LEGACY_DIRS", (str(legacy),))

    with session_factory() as db:
        assert backfill._delete_redundant_files(db, dry_run=False) == 1
    assert stranger.exists()


def test_a_dry_run_deletes_nothing(client, seeded, session_factory, tmp_path, monkeypatch):
    _, raw = enrolled(client, session_factory, "123457002")
    legacy = tmp_path / "samples"
    legacy.mkdir()
    copy = legacy / "copy.png"
    copy.write_bytes(raw)
    monkeypatch.setattr(backfill, "LEGACY_DIRS", (str(legacy),))

    with session_factory() as db:
        backfill._delete_redundant_files(db, dry_run=True)
    assert copy.exists()


def test_a_destroyed_key_makes_its_images_undeletable_rather_than_deletable(
        client, seeded, session_factory, tmp_path, monkeypatch):
    """After crypto-shredding the database can no longer reproduce the image, so a
    plaintext copy is exactly what must not be quietly removed as redundant — it is the
    only thing left, and someone has to look at it deliberately."""
    from backend.app.repositories import customer_keys

    customer_id, raw = enrolled(client, session_factory, "123457003")
    legacy = tmp_path / "samples"
    legacy.mkdir()
    orphan = legacy / "copy.png"
    orphan.write_bytes(raw)
    monkeypatch.setattr(backfill, "LEGACY_DIRS", (str(legacy),))

    with session_factory() as db:
        customer_keys.destroy(db, customer_id)
        db.commit()
        assert backfill._delete_redundant_files(db, dry_run=False) == 1
    assert orphan.exists()


def test_digests_cover_both_kinds_of_image(client, seeded, session_factory):
    """References and compared query images both count as reproducible."""
    from test_signature_core import make_signature
    from test_verify import png, verify

    customer_id, raw = enrolled(client, session_factory, "123457004")
    verify(client, "123457004", png(make_signature()))

    with session_factory() as db:
        digests = backfill._decrypted_digests(db)
    assert hashlib.sha256(raw).hexdigest() in digests

    from backend.app.models_db import Verification
    from backend.app.services.verification import decrypt_query_image
    with session_factory() as db:
        row = db.execute(select(Verification)).scalars().first()
        compared = decrypt_query_image(db, row)
    assert hashlib.sha256(compared).hexdigest() in digests
