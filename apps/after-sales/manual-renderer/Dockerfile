ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.55.0-noble
FROM ${PLAYWRIGHT_IMAGE}

ENV NODE_ENV=production
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /app

COPY apps/after-sales/manual-renderer/package.json apps/after-sales/manual-renderer/package-lock.json ./
RUN npm ci --omit=dev

COPY apps/after-sales/manual-renderer/renderer.js apps/after-sales/manual-renderer/renderer.test.js ./
COPY docker/backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 3000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["node", "renderer.js"]
