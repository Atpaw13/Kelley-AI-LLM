from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "knowledge"
DATA_DIR = ROOT / "data"
CHUNKS_PATH = DATA_DIR / "generated" / "chunks.jsonl"
CHROMA_PATH = Path(os.getenv("CHROMA_PATH", str(DATA_DIR / "chroma")))
if not CHROMA_PATH.is_absolute():
    CHROMA_PATH = ROOT / CHROMA_PATH
COLLECTION_NAME = os.getenv("KELLEY_CHROMA_COLLECTION", "kelley_sources")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def clean_text(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", " ", text or "")
    text = re.sub(r"\s+", " ", text or "")
    return text.strip()


def infer_section(text: str) -> str | None:
    if not text:
        return None
    candidates = re.findall(r"(?:^|\. )([A-Z][A-Za-z &/,-]{4,70})(?:\.|:|$)", text[:500])
    if candidates:
        return candidates[0].strip()
    words = text.split()
    return " ".join(words[:8]) if words else None


def chunk_page(text: str, size: int = 950, overlap: int = 160) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_text_links(text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_url in re.findall(r"https?://[^\s)>\]]+", text):
        url = raw_url.rstrip(".,;:")
        if url in seen:
            continue
        links.append({"label": url[:120], "url": url})
        seen.add(url)
    for email in re.findall(r"(?<![\w.-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        url = f"mailto:{email}"
        if url in seen:
            continue
        links.append({"label": email[:120], "url": url})
        seen.add(url)
    return links[:12]


def extract_page_links(page, text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in getattr(page, "hyperlinks", []) or []:
        url = item.get("uri") or item.get("url")
        if not url or url in seen:
            continue
        label = clean_text(item.get("text") or url)
        links.append({"label": label[:120], "url": url})
        seen.add(url)
    for annotation in getattr(page, "annots", []) or []:
        uri = (annotation.get("uri") or annotation.get("data", {}).get("A", {}).get("URI")) if annotation else None
        if not uri or uri in seen:
            continue
        links.append({"label": uri[:120], "url": uri})
        seen.add(uri)
    for item in extract_text_links(text):
        if item["url"] in seen:
            continue
        links.append(item)
        seen.add(item["url"])
    return links[:12]


def document_priority(pdf_path: Path, first_page_text: str) -> int:
    current_markers = ("2025/2026", "2025 - 2026", "2025-2026")
    if any(marker in first_page_text for marker in current_markers):
        return 2
    if "student organization handbook" in pdf_path.stem.lower():
        return 2
    return 3


def extract_chunks(pdf_path: Path) -> list[dict]:
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = clean_text(pdf.pages[0].extract_text() or "") if pdf.pages else ""
        priority = document_priority(pdf_path, first_page_text)
        for page_index, page in enumerate(pdf.pages, start=1):
            text = clean_text(page.extract_text() or "")
            if len(text) < 80:
                continue
            if pdf_path.name == "Kelley-Career-Guide.pdf" and page_index <= 2:
                continue
            if page_index <= 3 and "table of contents" in text.lower():
                continue
            section = infer_section(text)
            links = extract_page_links(page, text)
            for chunk_index, chunk in enumerate(chunk_page(text), start=1):
                chunks.append(
                    {
                        "id": f"{pdf_path.stem}-p{page_index}-c{chunk_index}",
                        "document": pdf_path.name,
                        "page": page_index,
                        "section": section,
                        "text": chunk,
                        "source_type": "Kelley Document",
                        "url": None,
                        "title": pdf_path.stem,
                        "heading": section,
                        "crawled_at": None,
                        "links": links,
                        "priority": priority,
                    }
                )
    return chunks


def write_jsonl(chunks: list[dict]) -> None:
    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def write_chroma(chunks: list[dict]) -> bool:
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        print(f"Chroma/local embedding packages unavailable; wrote JSONL fallback only. {exc}")
        return False

    model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    batch_size = 48
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        embeddings = model.encode([item["text"] for item in batch], show_progress_bar=False).tolist()
        collection.add(
            ids=[item["id"] for item in batch],
            documents=[item["text"] for item in batch],
            metadatas=[
                {
                    "document": item["document"],
                    "page": item["page"],
                    "section": item.get("section") or "",
                    "source_type": item.get("source_type") or "Kelley Document",
                    "url": item.get("url") or "",
                    "title": item.get("title") or item["document"],
                    "priority": item.get("priority", 3),
                }
                for item in batch
            ],
            embeddings=embeddings,
        )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Kelley PDFs into local ChromaDB.")
    parser.add_argument("--knowledge-dir", type=Path, default=KNOWLEDGE_DIR)
    args = parser.parse_args()

    pdfs = sorted(args.knowledge_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {args.knowledge_dir}")

    chunks = []
    for pdf_path in pdfs:
        print(f"Reading {pdf_path.name}")
        chunks.extend(extract_chunks(pdf_path))

    write_jsonl(chunks)
    chroma_ready = write_chroma(chunks)
    pages = {(chunk["document"], chunk["page"]) for chunk in chunks}
    print(f"Indexed {len(chunks)} chunks from {len(pdfs)} PDFs across {len(pages)} pages.")
    print(f"ChromaDB: {'ready' if chroma_ready else 'not created; JSONL fallback is available'}")
    print(f"Vector database location: {CHROMA_PATH}")


if __name__ == "__main__":
    main()
