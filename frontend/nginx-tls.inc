ssl_certificate     /etc/nginx/tls/server.crt;
ssl_certificate_key /etc/nginx/tls/server.key;
ssl_protocols       TLSv1.2 TLSv1.3;
ssl_ciphers         HIGH:!aNULL:!MD5;
ssl_session_cache   shared:SSL:10m;
