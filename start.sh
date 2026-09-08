#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
OLLAMA_URL="${OLLAMA_URL:-${OLLAMA_BASE_URL:-http://localhost:11434}}"
KELLEY_ENABLE_OLLAMA="${KELLEY_ENABLE_OLLAMA:-false}"

fail() {
  echo "Error: $1"
  exit 1
}

command -v node >/dev/null 2>&1 || fail "Node.js is not installed. Install Node.js, then rerun ./setup.sh."
command -v npm >/dev/null 2>&1 || fail "npm is not installed. Install npm, then rerun ./setup.sh."
command -v python3 >/dev/null 2>&1 || fail "Python 3 is not installed. Install Python 3, then rerun ./setup.sh."

[ -d backend ] || fail "Missing backend/ directory."
[ -d frontend ] || fail "Missing frontend/ directory."
[ -d knowledge ] || fail "Missing knowledge/ directory."
[ -d data ] || fail "Missing data/ directory."
[ -d backend/.venv ] || fail "Missing backend/.venv. Run ./setup.sh first."
[ -d frontend/node_modules ] || fail "Missing frontend/node_modules. Run ./setup.sh first."

if ! curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "Ollama is not running at $OLLAMA_URL. Start it with: ollama serve"
  if [ "$KELLEY_ENABLE_OLLAMA" = "true" ] || [ "$KELLEY_ENABLE_OLLAMA" = "1" ] || [ "$KELLEY_ENABLE_OLLAMA" = "yes" ]; then
    fail "KELLEY_ENABLE_OLLAMA is enabled, so Ollama must be reachable before starting."
  fi
  echo "Continuing because KELLEY_ENABLE_OLLAMA is disabled."
fi

cleanup() {
  echo
  echo "Stopping Kelley AI Prototype..."
  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

echo "Starting FastAPI backend on http://${BACKEND_HOST}:${BACKEND_PORT}"
(
  cd backend
  source .venv/bin/activate
  python -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
) &
BACKEND_PID=$!

echo "Starting Next.js frontend on http://localhost:${FRONTEND_PORT}"
(
  cd frontend
  npm run dev -- --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo
echo "Kelley AI Prototype is starting."
echo "Open http://localhost:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both servers."

wait "$BACKEND_PID" "$FRONTEND_PID"
