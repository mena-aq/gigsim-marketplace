# ADR 001: Runnable foundation

Accepted for Step 1: Next.js App Router with TypeScript; FastAPI; async SQLAlchemy
and Alembic on PostgreSQL; Arq on Redis; Chroma; Ollama. Python dependencies are
resolved by uv; npm locks the web dependencies. Node 22 is the frontend runtime.

Arq keeps the future async graph/MCP worker straightforward. Chroma runs as its
own service and keeps retrieval experiments independent of application tables.
Next.js matches the assignment's route layout and can access the API server-side
without exposing internal container addresses to browsers.

GigBid and GigSim have separate databases and volumes. Application models must
never import simulator models. Tenant-owned records reference users; composite
foreign keys prevent linking a proposal or pipeline card to another user's job.
Queries will also need tenant predicates when business routes are implemented.

Full authentication, OAuth encryption, graph checkpoints, memory, MCP services,
retrieval, tracing, and all product workflows are subsequent milestones. The web
shell reports real API readiness and does not simulate those workflows.

## Existing host model

The user already runs Ollama with `qwen2.5:3b`. The `ollama` Compose service
is a Linux host-network TCP bridge to that service, using the existing Python
image instead of downloading a duplicate Ollama image/model. Containers reach
it through `host.docker.internal:11435`. Host Ollama stays bound to loopback.
