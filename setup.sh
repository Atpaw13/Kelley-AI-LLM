#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    echo "Install $2, then rerun ./setup.sh."
    exit 1
  fi
}

need_command git "Git"
need_command python3 "Python 3"
need_command node "Node.js"
need_command npm "npm"

mkdir -p data/generated data/chroma knowledge logs

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [ ! -f backend/.env ]; then
  cp .env.example backend/.env
  echo "Created backend/.env from .env.example"
fi

if [ ! -f frontend/.env.local ]; then
  printf "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000\n" > frontend/.env.local
  echo "Created frontend/.env.local"
fi

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
  echo "Created Python virtual environment at backend/.venv"
fi

source backend/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

(cd frontend && npm install)

cat <<'MSG'

Setup complete.

Next steps:
1. Place approved Kelley PDFs in knowledge/
2. Run ./ingest.sh
3. Start Ollama if you plan to enable local generation: ollama serve
4. Run ./start.sh
MSG
