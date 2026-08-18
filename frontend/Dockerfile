FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
RUN apk add --no-cache openssl
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-static.inc /etc/nginx/securesign-static.inc
COPY nginx-tls.inc /etc/nginx/securesign-tls.inc
COPY nginx-headers.inc /etc/nginx/securesign-headers.inc
COPY tls-cert.sh /docker-entrypoint.d/10-securesign-tls-cert.sh
RUN chmod +x /docker-entrypoint.d/10-securesign-tls-cert.sh
COPY --from=build /app/dist /usr/share/nginx/html
