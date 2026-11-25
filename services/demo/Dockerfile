FROM nginx:alpine
COPY apps/site /usr/share/nginx/html
COPY apps/field /usr/share/nginx/html/field
COPY apps/explorer /usr/share/nginx/html/explorer
COPY apps/receipts/index.html apps/receipts/styles.css apps/receipts/config.js apps/receipts/app.js apps/receipts/receipts-core.js /usr/share/nginx/html/receipts/
COPY services/demo/nginx.conf /etc/nginx/conf.d/default.conf
