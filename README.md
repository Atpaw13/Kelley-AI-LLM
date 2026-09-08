# Kelley AI Prototype

A local proof-of-concept showing how Kelley students could ask simple questions and receive source-grounded answers from approved Kelley materials.

The prototype is intentionally small: a student asks a question, Kelley information is retrieved, a concise answer is returned, and authoritative sources are visible.

## Quick Start

```bash
git clone <repo-url>
cd kelley-ai-demo
./setup.sh
```

Place approved Kelley PDFs in `knowledge/`, then run:

```bash
./ingest.sh
ollama serve
./start.sh
```

Open:

```text
http://localhost:3000
```

Ollama is optional by default because `KELLEY_ENABLE_OLLAMA=false`. If you enable local generation, start Ollama before running the app.

## What This Prototype Demonstrates

- A Kelley-branded student information experience.
- Retrieval from local Kelley PDFs and curated official Kelley web pages.
- Answers that prefer retrieved evidence over plausible but unsupported claims.
- Visible source titles, page numbers when available, excerpts, and source links.
- A safer fallback when the prototype cannot verify an answer from available Kelley material.

## Architecture

```text
kelley-ai-demo/
  frontend/   Next.js, React, TypeScript, Tailwind CSS
  backend/    FastAPI API and answer orchestration
  knowledge/  Local source PDFs supplied by the user
  scripts/    PDF ingestion and curated Kelley web crawler
  data/       Generated retrieval files and optional Chroma index
```

The backend loads generated JSONL chunks from `data/generated/`. If ChromaDB and the embedding model are available, `scripts/ingest.py` also writes a local vector index in `data/chroma/`.

## Requirements

Install these separately before setup:

- Git
- Node.js and npm
- Python 3
- Ollama, only if you plan to enable local LLM generation

The setup script does not install system-level software.

## First-Time Setup

From the project root:

```bash
./setup.sh
```

This script:

- creates `backend/.venv`
- installs Python dependencies from `backend/requirements.txt`
- installs frontend dependencies from `frontend/package-lock.json`
- creates local `.env`, `backend/.env`, and `frontend/.env.local` files when missing
- creates expected local folders

## Adding Knowledge Sources

Place approved Kelley PDFs in:

```text
knowledge/
```

PDFs are ignored by Git. See `knowledge/README.md` for the expected source document location.

The curated web crawler is intentionally limited to approved Kelley domains and undergraduate-relevant paths:

- `https://kelley.iu.edu`
- `https://careers.kelley.iu.edu`

It respects `robots.txt`, preserves canonical URLs and source metadata, and avoids broad external crawling.

## Running Ingestion

```bash
./ingest.sh
```

This ingests:

- PDFs in `knowledge/`
- curated Kelley website content through `scripts/crawl_web.py`

At the end it prints:

- documents processed
- pages processed
- chunks created
- vector database location
- JSONL retrieval file location

## Running The App

```bash
./start.sh
```

This script checks for required tools and folders, verifies the backend virtual environment, checks whether Ollama is reachable, starts FastAPI and Next.js, and stops both processes when you press `Ctrl+C`.

Visit:

```text
http://localhost:3000
```

Backend health endpoint:

```text
http://127.0.0.1:8000/health
```

## Rebuilding The Knowledge Index

```bash
./rebuild.sh
```

This asks for confirmation, deletes only generated retrieval/index data in `data/generated/` and `data/chroma/`, then reruns ingestion.

It does not delete original PDFs in `knowledge/`.

## GitHub Workflow

Recommended first push:

```bash
git init
git branch -M main
git add .
git commit -m "Initial Kelley AI prototype"
gh repo create kelley-ai-demo --private --source=. --remote=origin --push
```

If you do not use GitHub CLI, create a private empty repository on GitHub, then run:

```bash
git remote add origin <repo-url>
git push -u origin main
```

Generated files, local env files, dependencies, and PDFs are excluded by `.gitignore`.

## Troubleshooting

If `./start.sh` says `backend/.venv` is missing:

```bash
./setup.sh
```

If Ollama is not running:

```bash
ollama serve
```

If local generation is enabled, confirm the model is available:

```bash
ollama pull llama3.1:8b
```

If the app has no sources:

```bash
ls knowledge/
./ingest.sh
```

If port `3000` or `8000` is already in use, stop the existing process or change `FRONTEND_PORT` / `BACKEND_PORT` in `.env`.

## Current Limitations

- This is not an official Kelley service.
- Source coverage is limited to local PDFs and the curated Kelley web crawl.
- Generated retrieval files are local and should be rebuilt after source changes.
- The safe default uses deterministic, evidence-bound synthesis for the known demo questions.
- Local Ollama generation is optional and should only be enabled after validating retrieved sources and prompts.
