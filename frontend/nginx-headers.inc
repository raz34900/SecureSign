# Included by the server block AND by every location that sets an add_header of its own.
# nginx does not merge add_header: a child block that declares one discards every header
# inherited from its parent. The static locations set Cache-Control, which silently threw
# away HSTS on the page users actually load - only /api/ ever received it.

# Short max-age on purpose: HSTS is pinned per host and ignores the port, so a long pin
# on localhost would outlive this self-signed certificate on every other port a developer
# serves from. Raise it with a real certificate on a real name.
add_header Strict-Transport-Security "max-age=300" always;

add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "no-referrer" always;

# img-src needs both data: and blob:, and neither is laxness. Prepared regions and the
# compared image arrive as base64 PNGs (data:), while the preview of the photograph the
# user just picked is a URL.createObjectURL of the File itself (blob:) - enrol, verify
# and the capture quality check all rely on it. 'unsafe-inline' for style-src covers
# Vue's :style bindings, which are style attributes; scripts stay strictly 'self'.
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" always;
