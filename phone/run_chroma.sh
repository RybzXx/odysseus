#!/bin/bash
# Run inside Ubuntu. Preserve the existing persistent vector store.
set -eu
export ANONYMIZED_TELEMETRY=False
exec /root/odysseus/venv/bin/chroma run \
    --path /data/data/com.termux/files/home/odysseus-data/chroma \
    --host 127.0.0.1 --port 8100
