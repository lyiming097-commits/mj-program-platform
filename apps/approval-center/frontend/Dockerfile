ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
ARG NGINX_IMAGE=docker.m.daocloud.io/library/nginx:1.27-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /app
ARG NPM_REGISTRY=https://registry.npmmirror.com
COPY apps/approval-center/frontend/package.json apps/approval-center/frontend/package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" && npm ci
COPY apps/approval-center/frontend ./
COPY packages/platform-ui /platform-ui
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM ${NGINX_IMAGE}
COPY apps/approval-center/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
