FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html styles.css app.js config.js /usr/share/nginx/html/
COPY docker-entrypoint.d/40-write-config.sh /docker-entrypoint.d/40-write-config.sh
RUN chmod 755 /docker-entrypoint.d/40-write-config.sh

EXPOSE 8090
