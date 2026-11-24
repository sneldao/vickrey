FROM nginx:1.27-alpine

COPY apps/explorer/nginx.conf /etc/nginx/conf.d/default.conf
COPY apps/explorer/index.html apps/explorer/styles.css apps/explorer/app.js apps/explorer/config.js apps/explorer/og-cover.png /usr/share/nginx/html/
COPY apps/field/trust.js apps/field/disclosure.js /usr/share/nginx/html/field/
COPY apps/explorer/docker-entrypoint.d/40-write-config.sh /docker-entrypoint.d/40-write-config.sh
RUN chmod 755 /docker-entrypoint.d/40-write-config.sh

EXPOSE 8090
