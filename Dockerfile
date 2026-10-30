# Navi bot image. Builds on amd64 (local) and arm64 (Graviton t4g.micro): `docker buildx build --platform linux/arm64 .`
FROM python:3.11-slim

ARG TARGETARCH
# Litestream release assets are named ...-linux-x86_64.tar.gz / ...-linux-arm64.tar.gz
ARG LITESTREAM_VERSION=0.5.17

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates sqlite3 awscli \
 && case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      amd64|x86_64) LS_ARCH=x86_64 ;; \
      arm64|aarch64) LS_ARCH=arm64 ;; \
      *) echo "unsupported architecture ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/ls.tar.gz \
    "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-${LS_ARCH}.tar.gz" \
 && tar -C /usr/local/bin -xzf /tmp/ls.tar.gz litestream && rm /tmp/ls.tar.gz \
 && litestream version \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY navi/ navi/
COPY docker/litestream.yml /etc/litestream.yml
COPY docker/entrypoint.sh /entrypoint.sh

# The container runs as uid 10001; the host mounts /var/lib/navi (owned by that uid) at /app/data.
RUN useradd -r -u 10001 navi && mkdir -p /app/data && chown -R navi /app/data && chmod +x /entrypoint.sh
USER navi
ENV PYTHONUNBUFFERED=1
STOPSIGNAL SIGTERM
CMD ["/entrypoint.sh"]
