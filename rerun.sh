#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "⏹  Stopping..."
docker compose down

echo "🔨  Rebuilding..."
docker compose build

echo "▶  Starting..."
docker compose up -d

echo "📋  Logs (Ctrl-C to exit):"
docker compose logs -f
