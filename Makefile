.PHONY: up down restart logs ps test clean-data

# Start the full stack (frontend :3000, backend :8000).
up:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example - add your API keys, then run 'make up' again." && exit 1)
	docker compose up -d --build
	@echo "Frontend: http://localhost:3000   Backend: http://localhost:8000/health"

# Stop the stack. Conversation data stays in the app_data volume.
down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

# Backend tests in a Linux container (fake provider, no API keys or quota used).
# Works on any OS, including Windows machines whose app-control policy blocks
# LiteLLM's native extension.
test:
	docker build --target test -t resilientai-backend-test ./backend
	docker run --rm resilientai-backend-test

# DANGER: deletes all stored conversations.
clean-data:
	docker compose down -v
