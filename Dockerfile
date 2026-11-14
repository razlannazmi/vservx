# Build the web app. Its output is platform-independent, so it always runs on the build host.
FROM --platform=$BUILDPLATFORM node:22-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim

COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

# systemctl, for reading the host's units over D-Bus.
RUN apt-get update \
    && apt-get install --no-install-recommends -y systemd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/ /tmp/backend/
RUN pip install --no-cache-dir /tmp/backend && rm -rf /tmp/backend
COPY --from=ui /ui/dist /app/ui/dist

# Fixed UID unlikely to exist on a host. Non-root, so systemd's polkit allows reading units only.
RUN useradd --uid 10001 --no-create-home vservx \
    && mkdir /data \
    && chown vservx /data

ENV VSERVX_DATA_DIR=/data \
    VSERVX_UI_DIR=/app/ui/dist

VOLUME /data
EXPOSE 5325
USER vservx
CMD ["vservx", "serve"]
