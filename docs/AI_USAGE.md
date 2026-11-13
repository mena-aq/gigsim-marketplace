# AI Usage Disclosure

Record the AI coding assistant/tool used, the files or tasks it helped with, and at least
one incorrect suggestion you identified and corrected. You remain responsible for all code.

## Step 1 foundation

OpenAI Codex implemented the API readiness checks, app schema and migrations,
Arq worker smoke path, Next.js shell and generated contract tooling, Compose
services, lockfiles, tests, and setup/architecture documentation. Existing
GigSim source was preserved; its Docker dependency declaration gained the same
SQLAlchemy async extra needed by the application.

Correction during implementation: the initial dependency declaration used
plain SQLAlchemy, which omitted the greenlet dependency needed by async engine
support. The import failure was caught and the declaration changed to
`sqlalchemy[asyncio]`. Documentation also corrected an existing HTMX architecture
statement that conflicted with the assignment's React/Next.js requirement.

The user clarified that Ollama/qwen2.5:3b was already installed on the host.
A duplicate Ollama image pull exhausted disk space during verification; that
newly downloaded image was removed, the interrupted Compose write restored,
and the configuration changed to a small bridge to the existing host service.
The full stack and PostgreSQL tests were checked again after recovery.
