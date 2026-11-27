# The journal's public site (Next.js), as a small self-contained Node server.
# Build from the repository root:  docker build -f site/Dockerfile .
#
# The build needs no API: pages are built empty and rebuilt from the API when the server starts
# (instrumentation.ts) and whenever the platform publishes something (/api/revalidate).
FROM node:22-alpine AS build
WORKDIR /src
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
COPY packages/api-client/package.json packages/api-client/
COPY workspace/package.json workspace/
COPY site/package.json site/
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

COPY biome.json ./
COPY packages ./packages
COPY site ./site
RUN npm run build --workspace @jps/site

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S site && adduser -S site -G site
# The standalone server keeps rebuilt pages in .next, so the directory belongs to the server's user.
COPY --from=build --chown=site:site /src/site/.next/standalone ./
COPY --from=build --chown=site:site /src/site/.next/static ./site/.next/static
USER site
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:3000/robots.txt || exit 1
CMD ["node", "site/server.js"]
