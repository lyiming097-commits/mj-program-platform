ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
ARG NGINX_IMAGE=docker.m.daocloud.io/library/nginx:1.27-alpine

FROM ${NGINX_IMAGE} AS build

ARG ALPINE_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/alpine

RUN sed -i "s|https://dl-cdn.alpinelinux.org/alpine|${ALPINE_MIRROR}|g; s|http://dl-cdn.alpinelinux.org/alpine|${ALPINE_MIRROR}|g" /etc/apk/repositories \
    && apk add --no-cache nodejs npm

WORKDIR /app

ARG NPM_REGISTRY=https://registry.npmmirror.com

COPY apps/cable-mall/frontend/package.json apps/cable-mall/frontend/package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" \
    && npm config set replace-registry-host always \
    && npm ci

COPY apps/cable-mall/frontend ./
COPY packages/platform-ui /platform-ui

ARG VITE_API_BASE_URL=
ARG VITE_DING_CLIENT_ID=
ARG VITE_DING_CORP_ID=
ARG VITE_DING_REDIRECT_URI=

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_DING_CLIENT_ID=${VITE_DING_CLIENT_ID}
ENV VITE_DING_CORP_ID=${VITE_DING_CORP_ID}
ENV VITE_DING_REDIRECT_URI=${VITE_DING_REDIRECT_URI}

RUN npm run build

FROM ${NGINX_IMAGE}

COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
