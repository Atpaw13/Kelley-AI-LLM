# Kelley Source Documents

Place approved Kelley source PDFs in this folder before running ingestion.

The prototype currently expects documents such as:

- `Kelley-Career-Guide.pdf`
- `The Kelley Playbook - Google Docs.pdf`

PDFs are intentionally ignored by Git so the repository can stay lightweight and avoid committing source documents that may need separate approval. After adding or replacing PDFs, run:

```bash
./ingest.sh
```
