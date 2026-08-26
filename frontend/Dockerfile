FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
RUN apk add --no-cache openssl
# The config is a template: the stock entrypoint runs envsubst over /etc/nginx/templates
# at start, writing conf.d/default.conf. These are the defaults for development; compose
# overrides them from .env at deployment (443 and the public domain).
ENV PUBLIC_TLS_PORT=8443 PUBLIC_SERVER_NAME=""
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY nginx-static.inc /etc/nginx/securesign-static.inc
COPY nginx-tls.inc /etc/nginx/securesign-tls.inc
COPY nginx-headers.inc /etc/nginx/securesign-headers.inc
COPY tls-cert.sh /docker-entrypoint.d/10-securesign-tls-cert.sh
RUN chmod +x /docker-entrypoint.d/10-securesign-tls-cert.sh
COPY --from=build /app/dist /usr/share/nginx/html
