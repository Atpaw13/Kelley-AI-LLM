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

[ -d backend/.venv ] || {
  echo "Missing backend/.venv. Run ./setup.sh first."
  exit 1
}

mkdir -p data/generated data/chroma

source backend/.venv/bin/activate

echo "Ingesting Kelley PDFs from knowledge/..."
python scripts/ingest.py

echo
echo "Crawling approved Kelley web sources..."
python scripts/crawl_web.py --max-pages "${KELLEY_WEB_MAX_PAGES:-80}" --delay "${KELLEY_WEB_DELAY:-0.25}"

echo
python - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
pdfs = sorted((root / "knowledge").glob("*.pdf"))
pdf_chunks = root / "data" / "generated" / "chunks.jsonl"
web_chunks = root / "data" / "generated" / "web_chunks.jsonl"

def load(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

pdf_items = load(pdf_chunks)
web_items = load(web_chunks)
pages = {(item.get("document"), item.get("page")) for item in pdf_items if item.get("page")}
web_pages = {item.get("url") for item in web_items if item.get("url")}

print("Ingestion summary")
print(f"- documents processed: {len(pdfs)} PDFs + {len(web_pages)} Kelley web pages")
print(f"- PDF pages processed: {len(pages)}")
print(f"- chunks created: {len(pdf_items) + len(web_items)}")
print(f"- vector database location: {root / 'data' / 'chroma'}")
print(f"- JSONL retrieval files: {root / 'data' / 'generated'}")
PY
