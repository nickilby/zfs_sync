.PHONY: help install install-dev test lint format clean docker-build docker-up docker-down docker-logs docker-shell

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

# Docker commands
docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-shell:
	docker-compose exec zfs-sync /bin/bash

