# GigBid Portfolio MCP

Read-only portfolio evidence server built with the official MCP Python SDK.
Tools: `search_evidence`, `get_case_study`, `list_skills`, `verify_claims`. Includes case/proposal
resource templates and a portfolio-grounded screening-answer prompt.

## Install and run

From a clone of this repository, follow `docs/RUNBOOK.md` to migrate the database,
provision MCP tokens, prepare a persona corpus, and run `make rag-models rag-ingest`. Then either use Compose
(`portfolio-mcp` on http://localhost:8101/mcp), or build and launch independently:

```bash
docker build -t gigbid-portfolio -f infra/docker/python.Dockerfile .
docker run --rm --network host --env-file .env \
  -e MCP_BASE_URL=http://localhost:8101 \
  -v "$PWD/data/personas:/app/data/personas:ro" \
  -v "$PWD/data/processed/rag:/app/data/processed/rag:ro" \
  gigbid-portfolio uvicorn mcp_servers.portfolio.server:create_app \
  --factory --host 127.0.0.1 --port 8101 --no-access-log
```

The standalone command targets Linux and uses the host-accessible Postgres URL
from `.env`. It shares the migrated GigBid database for credentials/audit. Attach
any MCP host supporting Streamable HTTP to the URL and supply
`Authorization: Bearer <your MCP token>` through its credential settings.
Do not embed credentials in a committed configuration or URL.

Sources live under `data/personas/<assigned persona>`; identity comes from the
token. Search uses the configured v0/v1/v2/v3/v8 backend, with V0 as the development
baseline. Host Ollama provides all-minilm embeddings/Qwen; the cross-encoder
uses local CPU ONNX artifacts. Configure CHROMA_HOST/CHROMA_PORT for the server
and retain access to the mounted model/index manifests.
Use returned item IDs to read complete case studies and chunk IDs for verification; URI-encode IDs in
resource URLs. Dates/outcomes absent from source metadata remain null.

See `docs/TOOLS.md` for schemas, trust boundary, annotations, errors, and tests.
