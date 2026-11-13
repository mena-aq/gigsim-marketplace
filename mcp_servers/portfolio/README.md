# GigBid Portfolio MCP

Read-only portfolio evidence server built with the official MCP Python SDK.
Tools: `search_evidence`, `get_case_study`, `list_skills`. Includes case/proposal
resource templates and a portfolio-grounded screening-answer prompt.

## Install and run

From a clone of this repository, follow `docs/RUNBOOK.md` to migrate the database,
provision MCP tokens, and prepare a persona corpus. Then either use Compose
(`portfolio-mcp` on http://localhost:8101/mcp), or build and launch independently:

```bash
docker build -t gigbid-portfolio -f infra/docker/python.Dockerfile .
docker run --rm --network host --env-file .env \
  -e MCP_BASE_URL=http://localhost:8101 \
  -v "$PWD/data/personas:/app/data/personas:ro" \
  gigbid-portfolio uvicorn mcp_servers.portfolio.server:create_app \
  --factory --host 127.0.0.1 --port 8101 --no-access-log
```

The standalone command targets Linux and uses the host-accessible Postgres URL
from `.env`. It shares the migrated GigBid database for credentials/audit. Attach
any MCP host supporting Streamable HTTP to the URL and supply
`Authorization: Bearer <your MCP token>` through its credential settings.
Do not embed credentials in a committed configuration or URL.

Sources live under `data/personas/<assigned persona>`; identity comes from the
token. Search currently uses lexical overlap and labels its backend accordingly.
Use returned evidence IDs to read complete case studies; URI-encode IDs in
resource URLs. Dates/outcomes absent from source metadata remain null.

See `docs/TOOLS.md` for schemas, trust boundary, annotations, errors, and tests.
