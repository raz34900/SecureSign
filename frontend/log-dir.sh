#!/bin/sh
# The log volume arrives owned by whoever created it on the host; the worker that opens
# the dated access files runs as nginx. Also the retention pass: dated files older than
# 30 days go, the error log and anything else stays.
mkdir -p /var/log/nginx
chown nginx /var/log/nginx 2>/dev/null || true
find /var/log/nginx -name 'access-*.log' -mtime +30 -delete 2>/dev/null || true
