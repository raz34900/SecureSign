"""Copy a SQLite registry into PostgreSQL, byte for byte.

    python scripts/migrate_sqlite_to_postgres.py --source data/securesign.db \
        --target postgresql+psycopg://securesign:...@localhost/securesign

Reports and changes nothing by default. `--apply` writes; `--verify` re-checks a database
that has already been written.

Three things about this data decide the whole design.

The signature images are sealed with their own row id as additional authenticated data, so
an id that changes in transit is an image that never decrypts again - with no error at
insert time and none until someone opens it months later. Rows are therefore written
through explicit INSERTs listing every column, never through the ORM, whose `default=_uuid`
and `default=_now` would quietly mint a new id and stamp migration time over the real one.

Timestamps are stored by SQLite without a zone but they are UTC instants, because every
writer in the application produces one. They are read, asserted naive, and bound as aware
UTC. Letting PostgreSQL apply its own zone to a naive value would shift every row by the
server offset, uniformly - which preserves ordering, so nothing on screen looks wrong,
while the retention purge starts destroying query images early.

Nothing is decrypted and nothing is re-encrypted. The keys are not needed to move the
bytes, and a migration holding plaintext national IDs is the thing this system is built to
avoid. Run --verify afterwards with the keys present to prove the move preserved them.
"""
import argparse
import hashlib
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, LargeBinary, select, text

from backend.app.db import Base, make_engine
from backend.app import models_db  # noqa: F401 - registers the tables

# FK order: a parent is always written before anything that points at it. PostgreSQL
# checks immediately and SQLAlchemy declares these NOT DEFERRABLE, so this is required.
ORDER = ["organisations", "users", "customers", "customer_keys", "consent_records",
         "reference_signatures", "verifications", "model_feedback", "audit_log"]

# Deliberately not copied. A token issued against the old database must not still open the
# new one, a migration is a planned sign-out for everybody, and every row here is a hash of
# a secret nobody can reproduce. Whoever was signed in signs in again.
SKIPPED = ["sessions"]


def _fail(message: str) -> None:
    sys.exit(f"error: {message}")


def _key(name: str) -> str:
    """The table's primary key column. customer_keys is keyed on customer_id, not id."""
    return list(Base.metadata.tables[name].primary_key.columns)[0].name


def preflight(source: sqlite3.Connection, *, drop_orphans: bool) -> dict[str, set[int]]:
    """Everything that must hold before a single row moves. Returns rowids to skip."""
    if source.execute("PRAGMA foreign_keys").fetchone()[0]:
        print("note: foreign keys are enforced on the source")

    duplicates = source.execute(
        "select national_id_index, count(*) from customers "
        "group by 1 having count(*) > 1").fetchall()
    if duplicates:
        # Two customer rows for one person. Skipping one silently discards their
        # references and history; this is a reconciliation decision for a human.
        _fail(f"{len(duplicates)} duplicate national_id_index value(s); resolve before migrating")

    # SQLite does not enforce foreign keys unless asked, and this database never asked, so
    # a deleted customer can leave children behind that PostgreSQL will refuse.
    orphans: dict[str, set[int]] = defaultdict(set)
    for table, rowid, parent, _ in source.execute("PRAGMA foreign_key_check").fetchall():
        orphans[table].add(rowid)
    if orphans:
        print("\norphan rows (parent no longer exists):")
        for table, rowids in sorted(orphans.items()):
            print(f"  {table}: {len(rowids)}")
        unreadable = _orphans_carry_no_ciphertext(source)
        print(f"  carrying readable ciphertext: {0 if unreadable else 'SOME'}")
        if not unreadable:
            _fail("some orphan rows hold ciphertext whose key still exists; "
                  "a human must decide what happens to that customer's data")
        if not drop_orphans:
            _fail("pass --drop-orphans to leave them behind, or repair the source first")
        print("  --drop-orphans given: they will not be copied\n")

    for table, column in [("customers", "national_id_encrypted"),
                          ("customer_keys", "wrapped_dek"),
                          ("reference_signatures", "image_encrypted"),
                          ("reference_signatures", "embedding"),
                          ("verifications", "query_image_encrypted")]:
        wrong = source.execute(
            f"select count(*) from {table} "
            f"where {column} is not null and typeof({column}) != 'blob'").fetchone()[0]
        if wrong:
            # A value inserted as str lands in a BLOB column as TEXT and reads back as str.
            _fail(f"{wrong} row(s) in {table}.{column} are not stored as blobs")

    return orphans


def orphan_keys(source: sqlite3.Connection) -> dict[str, set]:
    """Primary keys of rows whose parent is gone, so verification can tell a row that was
    deliberately left behind from one that went missing in transit."""
    out: dict[str, set] = defaultdict(set)
    for table, rowid, _parent, _fk in source.execute("PRAGMA foreign_key_check").fetchall():
        row = source.execute(
            f"select {_key(table)} from {table} where rowid = ?", (rowid,)).fetchone()
        if row:
            out[table].add(row[0])
    return out


def _orphans_carry_no_ciphertext(source: sqlite3.Connection) -> bool:
    """True when nothing readable is lost by dropping the orphans."""
    readable = source.execute("""
        select (select count(*) from reference_signatures r
                left join customers c on c.id = r.customer_id
                where c.id is null and r.image_encrypted is not null)
             + (select count(*) from verifications v
                left join customers c on c.id = v.customer_id
                where c.id is null and v.query_image_encrypted is not null)
             + (select count(*) from customer_keys k
                left join customers c on c.id = k.customer_id where c.id is null)
    """).fetchone()[0]
    return readable == 0


def _convert(value, column):
    """One SQLite value as PostgreSQL wants it. Nothing here may invent or discard."""
    if value is None:
        return None  # never coalesced: '' and NULL both occur and mean different things
    if isinstance(column.type, DateTime):
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            _fail(f"{column} holds a zone-carrying timestamp; this database should not")
        # .replace, never .astimezone: the stored wall clock is already UTC.
        return parsed.replace(tzinfo=timezone.utc)
    if isinstance(column.type, LargeBinary):
        return bytes(value)
    if isinstance(column.type, Boolean):
        return bool(value)
    return value


def copy(source: sqlite3.Connection, engine, orphans: dict[str, set[int]]) -> dict[str, int]:
    """Every table, in one transaction. It all lands or none of it does."""
    counts = {}
    with engine.begin() as connection:
        connection.execute(text("SET TIME ZONE 'UTC'"))
        zone = connection.execute(text("SHOW timezone")).scalar_one()
        if zone != "UTC":
            _fail(f"target session timezone is {zone}, not UTC")

        for name in ORDER:
            table = Base.metadata.tables[name]
            columns = list(table.columns)
            names = [c.name for c in columns]
            skip = orphans.get(name, set())

            rows = source.execute(
                f"select rowid, {', '.join(names)} from {name}").fetchall()
            payload = [tuple(_convert(v, c) for v, c in zip(row[1:], columns))
                       for row in rows if row[0] not in skip]

            if payload:
                placeholders = ", ".join(f":{n}" for n in names)
                # Taken from the table, not assumed: customer_keys is keyed on
                # customer_id, and naming the wrong column here is an error rather than a
                # silently wider match. Targeted at the primary key on purpose - a bare
                # DO NOTHING would also swallow a national_id_index collision, turning a
                # hard stop into silent data loss.
                key = ", ".join(c.name for c in table.primary_key.columns)
                statement = text(
                    f'INSERT INTO {name} ({", ".join(names)}) VALUES ({placeholders}) '
                    f"ON CONFLICT ({key}) DO NOTHING")
                connection.execute(statement, [dict(zip(names, r)) for r in payload])

            counts[name] = len(payload)
            dropped = f"  ({len(skip)} orphan(s) left behind)" if skip else ""
            print(f"  {name:24} {len(payload):>6}{dropped}")
    return counts


def digest_check(source: sqlite3.Connection, engine) -> bool:
    """Every ciphertext column, every row, hashed independently on each side."""
    dropped = orphan_keys(source)
    COLUMNS = [("customers", "national_id_encrypted"),
               ("customer_keys", "wrapped_dek"),
               ("reference_signatures", "image_encrypted"),
               ("reference_signatures", "embedding"),
               ("verifications", "query_image_encrypted")]
    ok = True
    with engine.connect() as connection:
        for table, column in COLUMNS:
            key = _key(table)
            want = {r[0]: hashlib.sha256(bytes(r[1])).hexdigest()
                    for r in source.execute(
                        f"select {key}, {column} from {table} where {column} is not null")
                    if r[0] not in dropped.get(table, ())}
            # Hashed by PostgreSQL from what it actually stored, not by us from what we
            # think we sent. sha256() is built in from version 11.
            got = {r[0]: r[1] for r in connection.execute(text(
                f"select {key}, encode(sha256({column}), 'hex') from {table} "
                f"where {column} is not null"))}
            missing = set(want) - set(got)
            differing = {k for k in set(want) & set(got) if want[k] != got[k]}
            status = "ok" if not missing and not differing else "MISMATCH"
            print(f"  {f'{table}.{column}':<44} {len(got):>5} rows  {status}")
            if missing:
                print(f"      {len(missing)} row(s) absent from the target")
            if differing:
                print(f"      {len(differing)} row(s) differ")
            ok = ok and not missing and not differing

        # A wrong length is not caught by a digest of the wrong thing, and a short
        # embedding is silently skipped by the reader rather than raising.
        for table, column, size in [("reference_signatures", "embedding", 512),
                                    ("customers", "national_id_encrypted", 37),
                                    ("customer_keys", "wrapped_dek", 60)]:
            bad = connection.execute(text(
                f"select count(*) from {table} "
                f"where {column} is not null and octet_length({column}) != {size}")).scalar_one()
            print(f"  {table}.{column} == {size} bytes: {'ok' if not bad else f'{bad} WRONG'}")
            ok = ok and not bad
    return ok


def timestamp_check(source: sqlite3.Connection, engine) -> bool:
    """The instant must survive. A uniform shift preserves ordering and hides itself."""
    dropped = orphan_keys(source)
    ok = True
    with engine.connect() as connection:
        for name in ORDER:
            table = Base.metadata.tables[name]
            stamps = [c.name for c in table.columns if isinstance(c.type, DateTime)]
            for column in stamps:
                key = _key(name)
                want = source.execute(
                    f"select {key}, {column} from {name} where {column} is not null "
                    f"order by {column} limit 3").fetchall()
                for row_id, raw in want:
                    if row_id in dropped.get(name, ()):
                        continue
                    got = connection.execute(text(
                        f"select to_char({column} at time zone 'UTC', "
                        f"'YYYY-MM-DD HH24:MI:SS.US') from {name} where {key} = :i"),
                        {"i": row_id}).scalar_one_or_none()
                    if got is None:
                        continue  # an orphan that was deliberately left behind
                    if got != str(raw):
                        print(f"  {name}.{column} {row_id[:8]}: {raw!r} -> {got!r}  SHIFTED")
                        ok = False
    print(f"  timestamps preserved to the microsecond: {'ok' if ok else 'FAILED'}")
    return ok


def decrypt_check(engine) -> bool:
    """The only test that proves the move preserved meaning rather than bytes.

    Runs against the target with the real keys. A digest check proves the ciphertext
    arrived; this proves it still decrypts, which is a different claim - the images are
    sealed with their row id as additional authenticated data, so an id that changed in
    transit produces bytes that verify perfectly and decrypt never.
    """
    from backend.app.config import get_settings
    from backend.app.db import make_session_factory
    from backend.app.models_db import Customer, ReferenceSignature
    from backend.app.repositories import customer_keys
    from backend.app.security import envelope
    from backend.app.security.crypto import blind_index, decrypt_pii

    settings = get_settings()
    if len(settings.pii_enc_key) != 64 or len(settings.pii_index_key) != 64:
        print("  skipped: SS_PII_ENC_KEY / SS_PII_INDEX_KEY not set in this shell")
        return True

    ok = True
    with make_session_factory(engine)() as db:
        for customer in db.execute(select(Customer)).scalars():
            try:
                plaintext = decrypt_pii(customer.national_id_encrypted, settings.pii_enc_key)
            except Exception:
                # Almost always the wrong key rather than damaged data - say so, because
                # the operator's next move differs completely between the two.
                print(f"  customer {customer.id[:8]}: did not decrypt "
                      f"(wrong SS_PII_ENC_KEY, or the ciphertext did not survive)")
                ok = False
                continue
            # The index too, not just the ciphertext: this is what proves both keys still
            # correspond to both columns together. "It decrypted" would not catch an
            # index that had been case-folded or truncated in transit.
            if not (plaintext.isdigit() and len(plaintext) == 9):
                print(f"  customer {customer.id[:8]}: national id did not decrypt"); ok = False
            elif blind_index(plaintext, settings.pii_index_key) != customer.national_id_index:
                print(f"  customer {customer.id[:8]}: blind index does not match"); ok = False
        print(f"  national ids decrypt and re-index: {'ok' if ok else 'FAILED'}")

        checked = 0
        for ref in db.execute(select(ReferenceSignature)).scalars():
            if not ref.image_encrypted:
                continue
            # existing_key_for, never key_for: key_for MINTS a key when none is found, so
            # a customer_keys row that failed to migrate would be silently replaced with a
            # brand new key and their images left permanently unreadable, reported as fine.
            try:
                dek = customer_keys.existing_key_for(db, ref.customer_id)
            except Exception:
                print(f"  reference {ref.id[:8]}: its customer key did not unwrap "
                      f"(wrong SS_PII_ENC_KEY, or wrapped_dek did not survive)")
                ok = False
                break
            if dek is None:
                print(f"  reference {ref.id[:8]}: no key for its customer"); ok = False
                continue
            try:
                envelope.decrypt_image(ref.image_encrypted, dek, aad=ref.id.encode())
                checked += 1
            except Exception:
                print(f"  reference {ref.id[:8]}: did not decrypt"); ok = False
        print(f"  {checked} reference image(s) decrypt under their own row id: "
              f"{'ok' if ok else 'FAILED'}")

        # Negative control. Without it every assertion above could be passing vacuously,
        # against a build where the AAD had been dropped and any ciphertext decrypts.
        ref = db.execute(select(ReferenceSignature)
                         .where(ReferenceSignature.image_encrypted.is_not(None))).scalars().first()
        if ref is not None and ok:
            dek = customer_keys.existing_key_for(db, ref.customer_id)
            try:
                envelope.decrypt_image(ref.image_encrypted, dek, aad=b"not-this-row")
                print("  negative control: wrong AAD DECRYPTED - binding is not in force")
                ok = False
            except Exception:
                print("  negative control: wrong AAD refused, as it must be")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="data/securesign.db")
    parser.add_argument("--target", required=True)
    parser.add_argument("--apply", action="store_true", help="write; otherwise report only")
    parser.add_argument("--verify", action="store_true", help="check an already-written target")
    parser.add_argument("--drop-orphans", action="store_true",
                        help="do not copy rows whose parent no longer exists")
    args = parser.parse_args()

    # Read-only, and never modified: the source file is the rollback plan.
    source = sqlite3.connect(f"file:{args.source}?mode=ro", uri=True)
    engine = make_engine(args.target)

    if args.verify:
        print("verifying:")
        ok = (digest_check(source, engine) & timestamp_check(source, engine)
              & decrypt_check(engine))
        sys.exit(0 if ok else "verification FAILED")

    print(f"source: {args.source}\ntarget: {engine.url.render_as_string(hide_password=True)}\n")
    orphans = preflight(source, drop_orphans=args.drop_orphans)

    print("rows to copy:")
    for name in ORDER:
        total = source.execute(f"select count(*) from {name}").fetchone()[0]
        print(f"  {name:24} {total - len(orphans.get(name, set())):>6}")
    for name in SKIPPED:
        total = source.execute(f"select count(*) from {name}").fetchone()[0]
        print(f"  {name:24} {'skipped':>6}  ({total} row(s) not copied, by design)")

    if not args.apply:
        print("\nnothing written. Re-run with --apply once the API is stopped.")
        return

    print("\ncopying:")
    copy(source, engine, orphans)
    print("\nverifying:")
    if not (digest_check(source, engine) & timestamp_check(source, engine)
            & decrypt_check(engine)):
        sys.exit("verification FAILED - do not point production at this database")
    print("\ndone. Keep the SQLite file read-only until the retention window has turned over.")


if __name__ == "__main__":
    main()
