#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "⏹  Stopping..."
docker compose -f docker-compose.build.yaml down

echo "🔨  Rebuilding..."
docker compose -f docker-compose.build.yaml build

echo "▶  Starting..."
docker compose -f docker-compose.build.yaml up -d

echo "📋  Logs (Ctrl-C to exit):"
docker compose -f docker-compose.build.yaml logs -f
