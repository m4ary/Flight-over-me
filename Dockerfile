FROM python:3.12-slim

ARG SHOUTRRR_VERSION=0.8.0
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && ARCH=$(case "${TARGETARCH}" in arm64) echo "arm64";; armv7*|armhf) echo "armv6";; *) echo "amd64";; esac) \
    && curl -fsSL "https://github.com/containrrr/shoutrrr/releases/download/v${SHOUTRRR_VERSION}/shoutrrr_linux_${ARCH}.tar.gz" \
       -o /tmp/shoutrrr.tar.gz \
    && tar -xzf /tmp/shoutrrr.tar.gz -C /usr/local/bin shoutrrr \
    && chmod +x /usr/local/bin/shoutrrr \
    && rm /tmp/shoutrrr.tar.gz \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["python", "-u", "main.py"]
