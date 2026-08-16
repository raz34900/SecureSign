#!/usr/bin/env sh
# Self-signed certificate for local TLS. Browsers will warn, which is correct for a
# certificate nobody vouched for. Production replaces these two files with a real
# certificate and needs no configuration change.
set -eu
DIR="$(dirname "$0")"
if [ -f "$DIR/server.crt" ] && [ -f "$DIR/server.key" ]; then
  echo "certificate already present at $DIR/server.crt"
  exit 0
fi
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout "$DIR/server.key" -out "$DIR/server.crt" \
  -subj "/CN=localhost/O=SecureSign" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 600 "$DIR/server.key"
echo "wrote $DIR/server.crt and $DIR/server.key"
