.PHONY: frontend backend worker docker dev

frontend:
	cd meeting_ai_frontend && npm run build

backend:
	uvicorn main:app --reload

docker:
	docker compose up -d

celery:
	celery -A app.celery_app.celery worker --loglevel=info --pool=solo

celery-beat:
	celery -A app.celery_app.celery beat --loglevel=info

dev:
	make docker
	make frontend
	make celery &
	make celery-beat &
	make backend

res:
	make frontend
	make backend