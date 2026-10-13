FROM debian:trixie

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 \
    && mkdir -p /run/cloud-init \
    && rm -rf /var/lib/apt/lists/*
