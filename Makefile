.PHONY: help install dev test lint format verify-db docker-up docker-down docker-logs

help: ## Muestra los comandos disponibles
	@echo "Comandos disponibles:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Instala dependencias del backend
	cd backend && pip install -r requirements.txt && pip install ruff pytest

dev: ## Inicia el servidor de desarrollo local
	cd backend && PYTHONPATH=. uvicorn app.main:app --reload --port 8000

test: ## Ejecuta la suite de pruebas unitarias
	cd backend && PYTHONPATH=. pytest

lint: ## Ejecuta el linter Ruff
	cd backend && ruff check .

format: ## Formatea el código con Ruff
	cd backend && ruff format .

verify-db: ## Verifica la configuración e índices de PostgreSQL
	cd backend && python scripts/verificar_db.py

docker-up: ## Levanta todo el stack con Docker Compose
	docker-compose up --build -d

docker-down: ## Detiene y destruye los contenedores de Docker
	docker-compose down

docker-logs: ## Muestra los logs de los contenedores Docker
	docker-compose logs -f
