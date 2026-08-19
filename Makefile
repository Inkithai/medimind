# MediMind — developer convenience targets
# ------------------------------------------
# Run from the repository root. Backend commands assume you are inside the
# `backend/` directory or that `backend` is on PYTHONPATH.

.PHONY: lint lint-backend lint-frontend format format-backend test test-backend test-frontend install

## Lint: backend (ruff) + frontend (eslint/prettier)
lint: lint-backend lint-frontend

lint-backend:
	ruff check backend/

lint-frontend:
	cd frontend && npx eslint src --max-warnings=0

format: format-backend

format-backend:
	cd backend && ruff format .

## Tests
test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest tests/

test-frontend:
	cd frontend && npm test

## Install
install:
	cd backend && pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install
