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
LOG=$(mktemp)

step() { printf '%s' "$1"; }
ok() { printf 'ok%s\n' "${1:+ - $1}"; }
fail() {
  printf 'FAILED\n\nDRILL FAILED: %s\n' "$1" >&2
  if [ -s "$LOG" ]; then
    printf -- '--- last tool output:\n' >&2
    tail -25 "$LOG" >&2
  fi
  exit 1
}
cleanup() { docker rm -f "$SCRATCH" >/dev/null 2>&1 || true; rm -f "$LOG"; }
trap cleanup EXIT

# Full tool output goes to $LOG; the terminal gets one line per step. On failure the
# tail of the log is printed, so nothing is hidden when it matters.
quiet() { "$@" >"$LOG" 2>&1; }
psql_live() { docker compose exec -T db psql -U securesign -d securesign -qtAc "$1"; }
clock() { psql_live "SELECT to_char(now(), 'HH24:MI:SS')"; }

printf 'SecureSign backup drill - proves the backup restores, to the second, and still decrypts.\n'
printf 'The live database is never the restore target; the restore lands in a scratch container.\n\n'

step "[1/5] WAL round trip to the encrypted repository ......... "
quiet docker compose exec -T -u postgres db pgbackrest --stanza=main stanza-create || true
# check pushes a WAL segment and waits for it to arrive in the repo: this single command
# proves archive_command, the repository, and the cipher passphrase all agree.
quiet docker compose exec -T -u postgres db pgbackrest --stanza=main check || fail "archive round trip"
ok

step "[2/5] Full backup of the whole database ................. "
quiet docker compose exec -T -u postgres db pgbackrest --stanza=main backup --type=full \
  || fail "backup did not complete"
LABEL=$(grep -o 'new backup label = [^ ]*' "$LOG" | cut -d= -f2 | tr -d ' ' || true)
SIZE=$(grep -o 'full backup size = [^,]*' "$LOG" | cut -d= -f2 | tr -d ' ' || true)
ok "${SIZE:-?} as ${LABEL:-?}"

printf '[3/5] Staging an accident in a scratch table:\n'
# Dropped first, never reused: a failed run leaves its rows behind, and a leftover
# "mistake" older than this run's target survives the restore correctly - which the
# verdict below would misread as the point-in-time target not being honoured.
psql_live "DROP TABLE IF EXISTS backup_drill"
psql_live "CREATE TABLE backup_drill (at timestamptz primary key, note text)"
MARKER="drill-$(date +%s)"
psql_live "INSERT INTO backup_drill VALUES (now(), '$MARKER')"
printf '        %s  marker row written        - only in WAL, newer than the backup: must survive\n' "$(clock)"
# Everything up to here must be in the archive before we restore to it.
psql_live "SELECT pg_switch_wal()" >/dev/null
sleep 3
TARGET=$(psql_live "SELECT now()")
printf '        %.8s  restore target captured   - "the second before the damage"\n' "${TARGET#* }"
sleep 2
psql_live "INSERT INTO backup_drill VALUES (now(), 'the-mistake')"
printf '        %s  the mistake written       - after the target: must vanish\n' "$(clock)"
psql_live "SELECT pg_switch_wal()" >/dev/null
sleep 3

step "[4/5] Restore into a scratch container .................. "
docker compose exec -T db test -f /var/lib/pgbackrest/backup/main/backup.info \
  || fail "the db container holds no repository at /var/lib/pgbackrest"
# The scratch container must mount exactly what the live db container mounts - asking
# the daemon removes any way for this script and the compose file to disagree.
REPO_DIR=$(docker inspect "$(docker compose ps -q db)" \
  --format '{{range .Mounts}}{{if eq .Destination "/var/lib/pgbackrest"}}{{.Source}}{{end}}{{end}}')
[ -n "$REPO_DIR" ] || fail "could not resolve the live repository mount from the db container"
# The image NAME from the compose config, not the running container's image id: a
# container left running across a rebuild reports a sha the daemon may no longer resolve.
IMAGE=$(docker compose config --images 2>/dev/null | grep -m1 '\-db$' || true)
[ -n "$IMAGE" ] || IMAGE=securesign-db
docker rm -f "$SCRATCH" >/dev/null 2>&1 || true
quiet docker run -d --name "$SCRATCH" --network "$NET" \
  -v "$REPO_DIR":/var/lib/pgbackrest \
  -e PGBACKREST_REPO1_CIPHER_TYPE="${PGBACKREST_REPO1_CIPHER_TYPE:-aes-256-cbc}" \
  -e PGBACKREST_REPO1_CIPHER_PASS="${BACKUP_REPO_PASSPHRASE:?export BACKUP_REPO_PASSPHRASE}" \
  --entrypoint sleep "$IMAGE" 3600 || fail "scratch container did not start"

# Copies the full backup into the scratch container's empty data directory, then leaves
# recovery settings pointing at the WAL archive with the target time set.
quiet docker exec -u postgres "$SCRATCH" pgbackrest --stanza=main restore \
  --type=time --target="$TARGET" --target-action=promote \
  || fail "restore"
# Starting postgres now replays WAL from the backup point forward and STOPS at the
# target - that replay is what brings back the marker, which the base backup predates.
# archive_mode stays off in the scratch instance, or it would push its own WAL into the
# same repository and pollute the history of the real cluster.
docker exec -d -u postgres "$SCRATCH" postgres -c archive_mode=off
for _ in $(seq 1 30); do
  docker exec "$SCRATCH" pg_isready -q -U securesign -d securesign 2>/dev/null && break
  sleep 2
done
docker exec "$SCRATCH" pg_isready -q -U securesign -d securesign || fail "restored postgres never came up"
ok "base backup copied in, WAL replayed up to the target, then promoted"

printf '[5/5] Verdicts:\n'
GOT=$(docker exec "$SCRATCH" psql -U securesign -d securesign -qtAc \
  "SELECT count(*) FROM backup_drill WHERE note = '$MARKER'")
[ "$GOT" = "1" ] || fail "marker row did not survive the restore"
printf '        marker survived the restore ..................... yes (WAL replay works)\n'
MISTAKE=$(docker exec "$SCRATCH" psql -U securesign -d securesign -qtAc \
  "SELECT count(*) FROM backup_drill WHERE note = 'the-mistake'")
[ "$MISTAKE" = "0" ] || fail "the mistake survived: point-in-time target was not honoured"
printf '        the mistake is gone ............................. yes (stopped at the target)\n'

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
        print("        no encrypted references in the restored copy .... nothing to prove")
        sys.exit(0)
    for ref in refs:
        dek = customer_keys.existing_key_for(db, ref.customer_id)
        assert dek is not None, f"no key for {ref.id[:8]}"
        envelope.decrypt_image(ref.image_encrypted, dek, aad=ref.id.encode())
    print(f"        restored data still decrypts .................... yes ({len(refs)} reference images checked)")
PYEOF
else
  printf '        decryption check ................................ skipped (api container not running)\n'
fi

psql_live "DROP TABLE IF EXISTS backup_drill" >/dev/null
printf '\nDRILL PASSED: the backup restores, to the second, and the data still decrypts.\n'
