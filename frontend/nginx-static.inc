client_max_body_size 12m;

# Hashed build assets never change under a given name — cache hard.
location /assets/ {
    root /usr/share/nginx/html;
    expires 1y;
    add_header Cache-Control "public, immutable";
    include /etc/nginx/securesign-headers.inc;
}

# index.html must never be cached, or a rebuild's new asset hashes are never fetched.
location / {
    root /usr/share/nginx/html;
    try_files $uri $uri/ /index.html;
    add_header Cache-Control "no-store";
    include /etc/nginx/securesign-headers.inc;
}
