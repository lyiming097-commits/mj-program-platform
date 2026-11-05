ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY apps/form-designer/frontend/package*.json ./
RUN npm ci
COPY packages/platform-ui /platform-ui
COPY apps/form-designer/frontend .
ENV MJ_PLATFORM_UI_PATH=/platform-ui/src
RUN npm run build
FROM ${NGINX_IMAGE}
COPY apps/form-designer/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
