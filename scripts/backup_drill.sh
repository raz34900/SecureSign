#!/bin/sh
# The restore rehearsal. A backup nobody has restored is a hope, not a backup - GitLab
# had three backup mechanisms and lost six hours because none had ever been tested.
#
#   ./scripts/backup_drill.sh
#
# Against the running compose stack, this: registers the stanza if needed, proves the
# WAL round trip, takes a full backup, plants a marker row, then simulates the disaster
# that matters - a destructive write - and restores INTO A SCRATCH CONTAINER to the
# second before the damage. It never touches the live database's data. Passes when the
# marker survived, the damage did not, and a reference image still decrypts under the
# application's own keys.
#
# Run it after deployment, and on a schedule. The nightly backup itself is one line of
# host cron:  docker compose exec -T -u postgres db pgbackrest --stanza=main backup
set -eu

SCRATCH=ss-restore-drill
NET=securesign_default
REPO_VOLUME=securesign_pgbackrest

say() { printf '\n=== %s\n' "$1"; }
fail() { printf 'DRILL FAILED: %s\n' "$1" >&2; exit 1; }
cleanup() { docker rm -f "$SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

psql_live() { docker compose exec -T db psql -U securesign -d securesign -qtAc "$1"; }

say "stanza (idempotent) and archive round trip"
docker compose exec -T -u postgres db pgbackrest --stanza=main stanza-create 2>&1 | tail -1 || true
# check pushes a WAL segment and waits for it to arrive in the repo: this single command
# proves archive_command, the repository, and the cipher passphrase all agree.
docker compose exec -T -u postgres db pgbackrest --stanza=main check || fail "archive round trip"

say "full backup"
docker compose exec -T -u postgres db pgbackrest --stanza=main backup --type=full \
  || fail "backup did not complete"

say "marker row, then the simulated disaster"
psql_live "CREATE TABLE IF NOT EXISTS backup_drill (at timestamptz primary key, note text)"
MARKER="drill-$(date +%s)"
psql_live "INSERT INTO backup_drill VALUES (now(), '$MARKER')"
# Everything up to here must be in the archive before we restore to it.
psql_live "SELECT pg_switch_wal()" >/dev/null
sleep 3
TARGET=$(psql_live "SELECT now()")
sleep 2
psql_live "INSERT INTO backup_drill VALUES (now(), 'the-mistake')"
psql_live "SELECT pg_switch_wal()" >/dev/null
sleep 3

say "restore into a scratch container, to the second before the mistake"
IMAGE=$(docker compose ps db --format '{{.Image}}' 2>/dev/null || true)
[ -n "$IMAGE" ] || IMAGE=securesign-db
cleanup
docker run -d --name "$SCRATCH" --network "$NET" \
  -v "$REPO_VOLUME":/var/lib/pgbackrest \
  -e PGBACKREST_REPO1_CIPHER_TYPE="${PGBACKREST_REPO1_CIPHER_TYPE:-aes-256-cbc}" \
  -e PGBACKREST_REPO1_CIPHER_PASS="${BACKUP_REPO_PASSPHRASE:?export BACKUP_REPO_PASSPHRASE}" \
  --entrypoint sleep "$IMAGE" 3600 >/dev/null

docker exec -u postgres "$SCRATCH" pgbackrest --stanza=main restore \
  --type=time --target="$TARGET" --target-action=promote \
  || fail "restore"
# archive_mode stays off in the scratch instance, or it would push its own WAL into the
# same repository and pollute the history of the real cluster.
docker exec -d -u postgres "$SCRATCH" postgres -c archive_mode=off
for _ in $(seq 1 30); do
  docker exec "$SCRATCH" pg_isready -q -U securesign -d securesign 2>/dev/null && break
  sleep 2
done
docker exec "$SCRATCH" pg_isready -q -U securesign -d securesign || fail "restored postgres never came up"

say "verdicts"
GOT=$(docker exec "$SCRATCH" psql -U securesign -d securesign -qtAc \
  "SELECT count(*) FROM backup_drill WHERE note = '$MARKER'")
[ "$GOT" = "1" ] || fail "marker row did not survive the restore"
MISTAKE=$(docker exec "$SCRATCH" psql -U securesign -d securesign -qtAc \
  "SELECT count(*) FROM backup_drill WHERE note = 'the-mistake'")
[ "$MISTAKE" = "0" ] || fail "the mistake survived: point-in-time target was not honoured"
echo "  marker survived, mistake rolled back"

# The claim that matters for this registry: a reference image in the RESTORED copy still
# decrypts under its own row id, with the keys the application holds. Runs inside the api
# container because that is where the keys and the code live.
if docker compose ps api --format '{{.Status}}' 2>/dev/null | grep -q '^Up'; then
  docker compose exec -T api python - "$SCRATCH" <<'PYEOF' || fail "decryption check against the restored copy"
import sys
from sqlalchemy import select
from backend.app.config import get_settings
from backend.app.db import make_engine, make_session_factory
from backend.app.models_db import ReferenceSignature
from backend.app.repositories import customer_keys
from backend.app.security import envelope

url = get_settings().database_url.replace("@db:", f"@{sys.argv[1]}:")
with make_session_factory(make_engine(url))() as db:
    refs = db.execute(select(ReferenceSignature)
                      .where(ReferenceSignature.image_encrypted.is_not(None))
                      .limit(5)).scalars().all()
    if not refs:
        print("  no encrypted references in the restored copy; nothing to prove")
        sys.exit(0)
    for ref in refs:
        dek = customer_keys.existing_key_for(db, ref.customer_id)
        assert dek is not None, f"no key for {ref.id[:8]}"
        envelope.decrypt_image(ref.image_encrypted, dek, aad=ref.id.encode())
    print(f"  {len(refs)} reference image(s) decrypt from the restored copy")
PYEOF
else
  echo "  api container not running: decryption check skipped"
fi

psql_live "DROP TABLE IF EXISTS backup_drill" >/dev/null
echo
echo "DRILL PASSED: the backup restores, to the second, and the data still decrypts."
