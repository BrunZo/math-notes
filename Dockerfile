FROM python:3.12-slim

ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates fontconfig \
    && TECTONIC_ARCH=$([ "$TARGETARCH" = "arm64" ] && echo "aarch64" || echo "x86_64") \
    && curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-${TECTONIC_ARCH}-unknown-linux-musl.tar.gz" \
       | tar -xz -C /usr/local/bin \
    && apt-get purge -y --auto-remove curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY config/ config/
COPY latex/ latex/
COPY workflow/ workflow/
COPY templates/ templates/
