#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "This will delete generated retrieval/index data in data/generated/ and data/chroma/."
echo "Original source documents in knowledge/ will not be deleted."
read -r -p "Continue? [y/N] " answer

case "$answer" in
  y|Y|yes|YES)
    ;;
  *)
    echo "Rebuild cancelled."
    exit 0
    ;;
esac

rm -rf data/generated data/chroma
mkdir -p data/generated data/chroma

if ./ingest.sh; then
  echo
  echo "Knowledge index rebuilt successfully."
else
  echo
  echo "Knowledge index rebuild failed."
  exit 1
fi
