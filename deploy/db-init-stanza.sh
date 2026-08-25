#!/bin/sh
# Runs once, on first cluster initialisation, while the entrypoint's temporary server is
# up. Registers the pgBackRest stanza so the very first archive_command has somewhere to
# push. Existing clusters are handled by scripts/backup_drill.sh instead.
set -e
pgbackrest --stanza=main stanza-create
