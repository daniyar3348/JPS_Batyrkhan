# Editorial workspace: a static build served by nginx, which also proxies the API.
# Build from the repository root:  docker build -f workspace/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /src

COPY package.json package-lock.json ./
COPY packages/api-client/package.json packages/api-client/
COPY workspace/package.json workspace/
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

COPY biome.json ./
COPY packages ./packages
COPY workspace ./workspace
RUN npm run build --workspace @jps/workspace

FROM nginx:1.29-alpine
COPY deploy/nginx/workspace.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx/proxy-api.inc /etc/nginx/conf.d/proxy-api.inc
COPY deploy/nginx/proxy-public-cache.inc /etc/nginx/conf.d/proxy-public-cache.inc
COPY --from=build /src/workspace/dist /usr/share/nginx/html
