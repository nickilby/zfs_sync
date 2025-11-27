.PHONY: help install install-dev test lint format clean docker-build docker-up docker-down docker-logs docker-shell docker-clean docker-rebuild docker-deploy

help:
	@echo "ZFS Sync - Development Commands"
	@echo ""
	@echo "Local Development:"
	@echo "  make install       - Install production dependencies"
	@echo "  make install-dev   - Install development dependencies"
	@echo "  make test          - Run tests"
	@echo "  make lint          - Run linters"
	@echo "  make format        - Format code"
	@echo "  make clean         - Clean build artifacts"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build  - Build Docker image"
	@echo "  make docker-up     - Start container"
	@echo "  make docker-down   - Stop container"
	@echo "  make docker-logs   - View container logs"
	@echo "  make docker-shell  - Open shell in container"
	@echo "  make docker-clean  - Remove old containers and images"
	@echo "  make docker-rebuild - Clean and rebuild image (no cache)"
	@echo "  make docker-deploy - Full deployment: clean, rebuild, and start"

# Local development
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

test:
	pytest

lint:
	ruff check zfs_sync/
	mypy zfs_sync/

format:
	black zfs_sync/
	ruff check --fix zfs_sync/

clean:
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf build/ dist/ *.egg-info
	rm -rf .pytest_cache .coverage htmlcov

# Docker commands - support both docker-compose (v1) and docker compose (v2)
DOCKER_COMPOSE := $(shell command -v docker-compose 2> /dev/null || echo "docker compose")

docker-build:
	@if ! command -v docker > /dev/null 2>&1; then \
		echo "Error: Docker is not installed or not in PATH"; \
		echo "Please install Docker Desktop from https://www.docker.com/products/docker-desktop"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) build

docker-up:
	@if ! command -v docker > /dev/null 2>&1; then \
		echo "Error: Docker is not installed or not in PATH"; \
		echo "Please install Docker Desktop from https://www.docker.com/products/docker-desktop"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) up -d

docker-down:
	@if ! command -v docker > /dev/null 2>&1; then \
		echo "Error: Docker is not installed or not in PATH"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) down

docker-logs:
	@if ! command -v docker > /dev/null 2>&1; then \
		echo "Error: Docker is not installed or not in PATH"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) logs -f

docker-shell:
	@if ! command -v docker > /dev/null 2>&1; then \
		echo "Error: Docker is not installed or not in PATH"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) exec zfs-sync /bin/bash

docker-clean:
	@if ! command -v docker > /dev/null 2>&1; then \
		echo "Error: Docker is not installed or not in PATH"; \
		exit 1; \
	fi
	@echo "Cleaning old Docker artifacts..."
	$(DOCKER_COMPOSE) down 2>/dev/null || true
	docker rmi zfs_sync-zfs-sync 2>/dev/null || true
	docker rmi zfs-sync:latest 2>/dev/null || true
	@echo "Cleanup complete"

docker-rebuild: docker-clean
	@if ! command -v docker > /dev/null 2>&1; then \
		echo "Error: Docker is not installed or not in PATH"; \
		exit 1; \
	fi
	@echo "Rebuilding Docker image with --no-cache..."
	$(DOCKER_COMPOSE) build --no-cache
	@echo "Rebuild complete"

docker-deploy: docker-rebuild docker-up
	@echo "Deployment complete! Checking version..."
	@sleep 3
	@$(DOCKER_COMPOSE) logs zfs-sync | grep -i "Starting zfs-sync" | head -1 || echo "Container starting..."

