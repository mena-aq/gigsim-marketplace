# GigBid web shell

Next.js App Router + TypeScript. Node 22 is required for local commands.
Run `npm ci`, `npm run dev`; set `API_INTERNAL_URL` to the API URL reachable
from the Next.js server (default `http://localhost:8000`). Compose sets it to
`http://api:8000`. No browser-facing API URL or CORS setup is needed yet.

`npm run typecheck` and `npm run build` verify the app. Run `make api-client`
from the repo root after API schema changes. `openapi.json` and
`src/lib/api/schema.d.ts` are generated contracts; do not edit them manually.
The typed client in `src/lib/api/client.ts` is hand-written.

The shell reports infrastructure availability. Product screens, authentication,
streaming, and approval interactions are later milestones.
