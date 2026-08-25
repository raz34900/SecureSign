FROM postgres:16-alpine

# pgBackRest runs inside this image because archive_command runs wherever postgres runs:
# every WAL segment is pushed to the repository the moment postgres finishes it, which is
# what turns "nightly dump" into "restore to any second".
RUN apk add --no-cache pgbackrest

COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf

# The local repository path. With a cloud repo (repo1-type=s3 via environment) this stays
# as spool space; locally it is the repository itself, on a named volume.
RUN mkdir -p /var/lib/pgbackrest && chown postgres:postgres /var/lib/pgbackrest \
 && chmod 750 /var/lib/pgbackrest

# On a freshly initialised cluster, register the stanza before the first archive_command
# fires - otherwise postgres logs archive failures and retains WAL until someone runs it.
# An existing cluster gets the same call, idempotently, from scripts/backup_drill.sh.
COPY db-init-stanza.sh /docker-entrypoint-initdb.d/90-stanza.sh
