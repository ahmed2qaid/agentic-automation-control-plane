.PHONY: up down logs api-test web-build import-demo

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

api-test:
	cd apps/api && python -m pytest -q

web-build:
	cd apps/web && npm run build

import-demo:
	docker compose exec n8n n8n import:workflow --input=/workflows/guarded-action.json
