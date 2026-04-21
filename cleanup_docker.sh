#!/bin/bash
# Run as your regular user (no sudo needed with apt Docker).
# Only sudo usage is clearing the containerd task dir if it exists.
set -e

echo "==> Stopping all medx containers..."
docker stop medx-app medx-postgres 2>/dev/null || true
docker rm -f medx-app medx-postgres 2>/dev/null || true

echo "==> Removing stale containerd task directories (requires sudo)..."
TASK_DIR="/run/containerd/io.containerd.runtime.v2.task/moby"
if [ -d "$TASK_DIR" ] && [ -n "$(ls -A "$TASK_DIR" 2>/dev/null)" ]; then
  sudo rm -rf "$TASK_DIR"/* && echo "  cleared $TASK_DIR"
fi

echo "==> Removing app image..."
docker rmi medx-app 2>/dev/null || true

echo "==> Removing volumes (fresh DB)..."
docker volume rm medx_postgres-data medx_uploads 2>/dev/null || true

echo ""
echo "==> State after cleanup:"
docker ps -a
echo ""
echo "==> Now run:"
echo "    cd /home/mahesh/medx && docker compose up --build -d"
