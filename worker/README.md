# Arq worker

`make worker` consumes jobs using `REDIS_URL`. Compose runs this as a separate
service with an Arq health check. `make worker-smoke` enqueues a unique task and
waits for its receipt; it never contacts a marketplace or spends Connects.
Scouting schedules and durable graph execution are future milestones.
