.PHONY: install api test lint eval gigsim seed seed-reset download process personas personas-groq persona-prompts persona-import smoke

install:
	python -m pip install -e ".[dev]"

api:
	uvicorn apps.api.main:app --reload --port 8000

gigsim:
	uvicorn gigsim.main:app --reload --port 8081

seed:
	python -m gigsim.seed

seed-reset:
	python -m gigsim.seed --reset

download:
	python data/scripts/download.py

process:
	python data/scripts/process.py

personas:
	python data/scripts/generate_personas.py

personas-groq:
	python data/scripts/generate_personas.py --provider groq

persona-prompts:
	python data/scripts/generate_personas.py --emit-prompts

persona-import:
	python data/scripts/generate_personas.py --import-inbox

test:
	pytest -q

lint:
	ruff check .

eval:
	python -m evals.runners.run_demo_eval

smoke:
	./scripts/smoke_gigsim.sh
