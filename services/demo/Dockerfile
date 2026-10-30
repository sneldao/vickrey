FROM nginx:alpine
COPY apps/site /usr/share/nginx/html
COPY apps/field /usr/share/nginx/html/field
COPY apps/explorer /usr/share/nginx/html/explorer
COPY services/demo/nginx.conf /etc/nginx/conf.d/default.conf
