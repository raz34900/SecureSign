#!/bin/sh
# Runs from /docker-entrypoint.d before nginx starts. Everything is served over TLS, so
# a missing certificate is a failure to boot, not a reason to fall back to plain HTTP.
# Production mounts a real certificate over these two paths and this becomes a no-op.
set -eu
DIR=/etc/nginx/tls
if [ -f "$DIR/server.crt" ] && [ -f "$DIR/server.key" ]; then
  exit 0
fi
echo "no certificate at $DIR - generating a self-signed one for development"
mkdir -p "$DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout "$DIR/server.key" -out "$DIR/server.crt" \
  -subj "/CN=localhost/O=SecureSign" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 600 "$DIR/server.key"
