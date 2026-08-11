.PHONY: frontend frontend-dev backend worker docker dev dev-live run res

frontend:
	cd meeting_ai_frontend && npm run build

# Vite dev server (hot reload) on :5173. Used by `make dev-live`.
frontend-dev:
	cd meeting_ai_frontend && npm run dev

# ponytail: `python -m` not the Scripts\*.exe shims — Windows Smart App Control
# blocks those unsigned pip launchers (make e=4551). Works on Linux/mac too.
backend:
	python -m uvicorn main:app --reload

docker:
	docker compose up -d

celery:
	python -m celery -A app.celery_app.celery worker --loglevel=info --pool=solo

celery-beat:
	python -m celery -A app.celery_app.celery beat --loglevel=info

dev:
	make docker
	make frontend
	make celery &
	make celery-beat &
	make backend

res:
	make frontend
	make backend

# `make run` — same as `res`: build the SPA into dist/, then serve everything
# from FastAPI at http://localhost:8000 (single server, no hot reload).
run: res

# `make dev-live` — live development: Vite dev server (hot reload) on :5173
# in the background + backend on :8000. Open http://localhost:5173.
# Needs VITE_API_URL=http://localhost:8000 in meeting_ai_frontend/.env.
dev-live:
	cd meeting_ai_frontend && npm run dev &
	python -m uvicorn main:app --reload