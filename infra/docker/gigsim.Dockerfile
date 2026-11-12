# GigSim image — self-contained: only what the simulator needs to run.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]" \
    "sqlalchemy>=2.0" \
    asyncpg \
    pydantic-settings

COPY gigsim/ gigsim/

EXPOSE 8081

CMD ["uvicorn", "gigsim.main:app", "--host", "0.0.0.0", "--port", "8081"]
