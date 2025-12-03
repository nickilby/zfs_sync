# Project Setup Guide: Building a Production-Ready GitHub Repository

This guide documents the project structure, documentation standards, CI/CD workflows, testing strategies, and release management practices established in the zfs_sync repository. Use this as a blueprint when setting up new projects.

## 1. Repository Structure and Organization

### Core Directory Layout

```
project-root/
├── .github/
│   └── workflows/          # GitHub Actions CI/CD pipelines
├── alembic/                 # Database migrations (if applicable)
│   └── versions/
├── config/                  # Configuration files and examples
├── docs/                    # Documentation
│   └── templates/          # Template scripts and configs
├── scripts/                 # Utility scripts
├── tests/                   # Test suite
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   └── conftest.py         # Shared pytest fixtures
├── project_name/           # Main application package
│   ├── api/                # API layer (routes, schemas, middleware)
│   ├── config/             # Configuration management
│   ├── database/           # Database models and repositories
│   ├── models/             # Domain models
│   └── services/           # Business logic layer
├── .git/hooks/             # Git hooks (pre-commit, etc.)
├── Dockerfile              # Container image definition
├── docker-compose.yml      # Development Docker Compose
├── docker-compose.prod.yml # Production Docker Compose
├── Makefile                # Development commands
├── pyproject.toml          # Python project configuration
├── requirements.txt       # Production dependencies
├── requirements-dev.txt  # Development dependencies
├── README.md              # Main project documentation
├── ARCHITECTURE.md        # Architecture documentation
├── HOW_TO_USE.md          # User guide
└── QUICK_START.md         # Quick setup guide
```

### Key Principles

- **Separation of Concerns**: API, services, and data layers are clearly separated
- **Configuration Management**: Centralized config with environment variable support
- **Template Scripts**: Reusable scripts in `docs/templates/` for deployment
- **Test Organization**: Clear separation between unit and integration tests

## 2. Documentation Standards

### Required Documentation Files

#### README.md (Main Entry Point)

The README.md serves as the primary entry point for anyone discovering your project. It should include:

- **Project Overview**: Clear description of what the project does and why it exists
- **Architecture Summary**: High-level architecture with link to detailed ARCHITECTURE.md
- **Getting Started**: Quick instructions to get the project running
- **Development Workflow**: Instructions for local development vs Docker
- **Production Deployment**: Step-by-step deployment guide
- **Configuration Options**: How to configure the application
- **Troubleshooting**: Common issues and solutions
- **Links to Other Documentation**: References to ARCHITECTURE.md, HOW_TO_USE.md, etc.

**Example Structure:**

```markdown
# Project Name

Brief description of the project.

## Overview
Detailed overview of purpose and goals.

## Architecture
For comprehensive architecture documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Getting Started
[Quick start instructions]

## Development
[Local and Docker development instructions]

## Production Deployment
[Deployment guide]

## Configuration
[Configuration options]

## Troubleshooting
[Common issues and solutions]
```

#### ARCHITECTURE.md (Technical Deep Dive)

This document provides comprehensive technical documentation for developers and architects:

- **System Architecture Diagrams**: Visual representation of system components
- **Component Design**: Detailed breakdown of each component and its responsibilities
- **Data Flow Diagrams**: How data moves through the system
- **Database Schema Documentation**: Entity relationships, table structures, indexes
- **API Design**: RESTful endpoint documentation, request/response formats
- **Security Architecture**: Authentication, authorization, data security
- **Technology Stack**: All technologies used with justifications
- **Design Patterns**: Patterns used (Repository, Service Layer, Dependency Injection, etc.)
- **Future Enhancements**: Planned features and improvements

**Key Sections:**

- Overview
- System Architecture
- Component Design
- Data Flow
- Database Schema
- API Design
- Security Architecture
- Deployment Architecture
- Technology Stack
- Design Patterns
- Future Enhancements

#### HOW_TO_USE.md (User Guide)

A beginner-friendly guide for end users:

- **What is This?**: Simple explanation of the project
- **Getting Started**: Step-by-step setup instructions
- **Step-by-Step Setup**: Detailed walkthrough of initial configuration
- **Using the System**: Daily operations and common tasks
- **Common Tasks**: Examples of typical workflows
- **Automation Scripts**: Example scripts for automation
- **Troubleshooting**: User-facing troubleshooting guide
- **Quick Reference**: Tables of endpoints, status values, etc.

**Target Audience**: End users who need to use the system but may not be developers.

#### QUICK_START.md (Fast Setup)

A minimal guide for experienced users who want to get started quickly:

- **Platform-Specific Instructions**: Setup for Linux, macOS, Windows
- **Service Configuration**: systemd, launchd, or other service manager configs
- **Common Troubleshooting**: Quick fixes for common issues
- **Minimal Steps**: Only essential steps to get running

**Target Audience**: Experienced users who know what they're doing.

#### tests/README.md (Testing Guide)

Documentation for developers working on tests:

- **Test Suite Structure**: How tests are organized
- **Running Tests**: Commands to run different test suites
- **Test Fixtures**: Available fixtures and how to use them
- **Writing New Tests**: Guidelines and examples
- **Test Markers**: How to use pytest markers
- **Test Configuration**: pytest configuration details

**Target Audience**: Developers contributing to the codebase.

### Documentation Best Practices

1. **Multiple Entry Points**: Different docs for different audiences (users, developers, operators)
1. **Code Examples**: Include working examples in all guides
1. **Troubleshooting**: Document common issues and solutions in each relevant doc
1. **Version References**: Link to specific versions when relevant
1. **Visual Aids**: Use ASCII diagrams or mermaid diagrams for architecture and data flow
1. **Keep Updated**: Documentation should evolve with the codebase
1. **Cross-References**: Link between related documents

## 3. GitHub Actions CI/CD Pipeline

### Workflow Structure (`.github/workflows/ci.yml`)

The CI pipeline should include these jobs, configured to run in parallel where possible:

#### Test Job

**Configuration:**

- **Matrix Strategy**: Test across multiple Python versions (3.9, 3.10, 3.11, 3.12)
- **Coverage Reporting**: Generate coverage reports (XML, HTML, terminal)
- **Artifact Upload**: Store HTML coverage reports as artifacts (30-day retention)
- **Codecov Integration**: Upload coverage to Codecov for tracking
- **Triggers**: Run on PRs, pushes to main/master/develop branches, and manual dispatch

**Example Configuration:**

```yaml
test:
  name: Test Python ${{ matrix.python-version }}
  runs-on: ubuntu-latest
  strategy:
    matrix:
      python-version: ["3.9", "3.10", "3.11", "3.12"]
    fail-fast: false

  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
        cache: 'pip'
    - run: pip install -r requirements.txt -r requirements-dev.txt
    - run: pytest --cov=project_name --cov-report=xml --cov-report=html -v
    - uses: codecov/codecov-action@v3
      if: matrix.python-version == '3.11'
    - uses: actions/upload-artifact@v4
      if: matrix.python-version == '3.11'
      with:
        name: coverage-report
        path: htmlcov/
        retention-days: 30
```

#### Lint Job

**Configuration:**

- **Code Quality**: Run ruff for linting with auto-fix capabilities
- **Type Checking**: Run mypy for type checking (with continue-on-error for gradual adoption)
- **Format Checking**: Verify code formatting with black (fail on mismatch)
- **Fail Fast**: Should fail on formatting/linting errors to maintain code quality

**Example Configuration:**

```yaml
lint:
  name: Lint and Format Check
  runs-on: ubuntu-latest

  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: 'pip'
    - run: pip install -r requirements-dev.txt
    - run: ruff check project_name/ tests/
    - run: mypy project_name/
      continue-on-error: true
    - run: black --check project_name/ tests/
```

#### Docker Build Job

**Configuration:**

- **Dependency**: Runs after tests pass (`needs: [test]`)
- **Build Test**: Build Docker image and verify it works
- **Health Check**: Test API health endpoint in running container
- **Cache Strategy**: Use GitHub Actions cache for Docker layers to speed up builds

**Example Configuration:**

```yaml
docker-build:
  name: Docker Build Test
  runs-on: ubuntu-latest
  needs: [test]

  steps:
    - uses: actions/checkout@v4
    - uses: docker/setup-buildx-action@v3
    - uses: docker/build-push-action@v5
      with:
        context: .
        file: ./Dockerfile
        push: false
        load: true
        tags: project-name:test
        cache-from: type=gha
        cache-to: type=gha,mode=max
    - run: |
        docker run -d --name test-container -p 8000:8000 project-name:test
        sleep 10
        curl -f http://localhost:8000/api/v1/health || exit 1
        docker stop test-container
```

#### Security Scanning Job

**Configuration:**

- **Bandit**: Python security vulnerability scanner (runs on code)
- **Secret Scanning**: Use TruffleHog to detect committed secrets
- **Artifact Upload**: Store security reports as artifacts
- **Continue on Error**: Don't block pipeline but report issues for review

**Example Configuration:**

```yaml
security-scan:
  name: Security Scanning
  runs-on: ubuntu-latest

  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - run: pip install bandit
    - run: bandit -r project_name/ -f json -o bandit-report.json || true
    - uses: trufflesecurity/trufflehog@main
      with:
        path: ./
      continue-on-error: true
    - uses: actions/upload-artifact@v4
      with:
        name: bandit-security-report
        path: bandit-report.json
        retention-days: 30
```

#### Dependency Check Job

**Configuration:**

- **Vulnerability Audit**: Use pip-audit for dependency scanning
- **Production & Dev**: Check both requirements.txt and requirements-dev.txt
- **Critical Check**: Fail on critical/high severity vulnerabilities
- **Artifact Upload**: Store audit reports as artifacts

**Example Configuration:**

```yaml
dependency-check:
  name: Dependency Vulnerability Check
  runs-on: ubuntu-latest

  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - run: pip install pip-audit
    - run: pip-audit --requirement requirements.txt --format json --output audit-prod.json || true
    - run: pip-audit --requirement requirements.txt
    - run: |
        if grep -i "CRITICAL\|HIGH" audit-prod.json; then
          exit 1
        fi
```

#### Benchmark Job (Optional)

**Configuration:**

- **Conditional**: Run on PRs or manual dispatch only
- **Performance Tests**: Run benchmark tests if available
- **Results Upload**: Store benchmark results as artifacts

**Example Configuration:**

```yaml
benchmark:
  name: Performance Benchmarks
  runs-on: ubuntu-latest
  needs: [test]
  if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'

  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - run: pip install -r requirements.txt -r requirements-dev.txt
    - run: pytest --benchmark-only --benchmark-json=benchmark-results.json -m benchmark || echo "No benchmarks"
      continue-on-error: true
    - uses: actions/upload-artifact@v4
      with:
        name: benchmark-results
        path: benchmark-results.json
        retention-days: 90
```

#### Create Release Job

**Configuration:**

- **Trigger**: Only on pushes to main branch (`if: github.event_name == 'push' && github.ref == 'refs/heads/main'`)
- **Dependencies**: Requires all other jobs to pass (`needs: [test, lint, docker-build, security-scan, dependency-check]`)
- **Version Extraction**: Read version from source files (pyproject.toml or **init**.py)
- **Release Creation**: Automatically create draft GitHub releases
- **Changelog**: Generate release notes from commit messages since last release
- **Permissions**: Requires `contents: write` permission

**Key Steps:**

1. Extract version from source files
1. Check if release with that version already exists
1. Get commit messages since last release
1. Create draft release with changelog
1. Tag release with `v{version}` format

### Workflow Best Practices

1. **Parallel Execution**: Run independent jobs in parallel to reduce total CI time
1. **Conditional Steps**: Use `if` conditions for optional steps (e.g., only upload coverage for one Python version)
1. **Artifact Retention**: Set appropriate retention days for reports (30 days for coverage, 90 days for benchmarks)
1. **Error Handling**: Use `continue-on-error: true` for non-blocking checks (security scans, benchmarks)
1. **Cache Strategy**: Cache pip dependencies and Docker layers to speed up builds
1. **Security**: Never commit secrets; use GitHub Secrets for sensitive data
1. **Matrix Strategies**: Use matrix for testing multiple Python versions efficiently
1. **Fail Fast**: Critical checks (tests, linting) should fail the pipeline immediately

## 4. Testing Strategy

### Test Organization

```
tests/
├── conftest.py              # Shared fixtures and test configuration
├── unit/                    # Unit tests (isolated component tests)
│   ├── test_services/      # Service layer tests
│   │   └── test_*.py
│   └── test_repositories/  # Repository layer tests
│       └── test_*.py
└── integration/            # Integration tests
    └── test_api/           # API endpoint tests
        └── test_*.py
```

### Test Configuration (pyproject.toml)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--tb=short",
]
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "slow: Slow running tests",
    "benchmark: Performance benchmark tests",
    "database: Tests that require database access",
]
```

### Test Fixtures

**Database Fixtures**: Use in-memory SQLite for fast, isolated tests. Each test gets a fresh database session.

**Example conftest.py:**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from project_name.database.base import Base
from project_name.database.engine import get_db

# In-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def test_db():
    """Create a fresh database for each test."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)

@pytest.fixture
def test_client(test_db):
    """Create a test client with database override."""
    from project_name.api.app import app

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    from fastapi.testclient import TestClient
    return TestClient(app)
```

**Sample Data Fixtures**: Create reusable fixtures for common test entities.

**Example:**

```python
@pytest.fixture
def sample_system_data():
    """Sample data for creating test systems."""
    return {
        "hostname": "test-system",
        "platform": "linux",
        "connectivity_status": "online"
    }
```

### Testing Best Practices

1. **Coverage Goals**: Aim for high coverage on critical paths (80%+ for core business logic)
1. **Test Markers**: Use markers to categorize and filter tests (`@pytest.mark.unit`, `@pytest.mark.integration`)
1. **Fast Tests**: Use in-memory databases for speed; avoid external dependencies
1. **Integration Tests**: Test API endpoints end-to-end with real HTTP requests
1. **Fixture Reuse**: Create reusable fixtures for common test data
1. **Isolation**: Each test should be independent and not rely on other tests
1. **Arrange-Act-Assert**: Follow AAA pattern for clear test structure
1. **Test Naming**: Use descriptive test names that explain what is being tested

**Example Test:**

```python
@pytest.mark.unit
def test_system_repository_create(test_db, sample_system_data):
    """Test that system repository can create a new system."""
    # Arrange
    repo = SystemRepository(test_db)

    # Act
    system = repo.create(**sample_system_data)

    # Assert
    assert system.id is not None
    assert system.hostname == sample_system_data["hostname"]
    assert system.platform == sample_system_data["platform"]
```

## 5. Version Management and Release Toolkit

### Version Management Strategy

#### Version Storage Locations

The version should be stored in multiple locations to ensure consistency:

- `pyproject.toml`: `version = "0.1.38"`
- `project_name/__init__.py`: `__version__ = "0.1.38"`
- `project_name/config/settings.py`: `app_version: str = Field(default="0.1.38", ...)`
- `config/project_name.yaml.example`: `app_version: "0.1.38"`

#### Pre-commit Hook (`.git/hooks/pre-commit`)

The pre-commit hook automates several quality checks and version management:

1. **Version Incrementing**: Auto-increments patch version (0.1.4 → 0.1.5) on every commit
1. **Code Formatting**: Runs black on staged Python files
1. **Linting**: Runs ruff with auto-fix on staged files
1. **Markdown Linting**: Formats markdown files with mdformat
1. **File Staging**: Automatically stages updated files

**Key Features:**

- Cross-platform support (Linux/macOS/Windows)
- Graceful degradation if tools not installed (warns but continues)
- Clear error messages with instructions
- Can be bypassed with `git commit --no-verify` if needed

**Installation:**

```bash
# Make hook executable
chmod +x .git/hooks/pre-commit

# Or copy from template
cp .git/hooks/pre-commit.sample .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

**Hook Structure:**

1. Extract current version from pyproject.toml or **init**.py
1. Increment patch version
1. Update version in all files
1. Stage updated version files
1. Run black on staged Python files
1. Run ruff on staged Python files
1. Run mdformat on staged Markdown files
1. Stage any auto-fixed files

### Release Process

#### Automated Release Creation

The GitHub Actions workflow automatically handles release creation:

1. **Version Extraction**: Reads version from `project_name/__init__.py` or `pyproject.toml`
1. **Release Check**: Checks if release with that version already exists
1. **Changelog Generation**: Gets commit messages since last release tag
1. **Draft Release**: Creates draft GitHub release with tag `v{version}`
1. **Release Notes**: Includes commit history in release body

**Release Workflow Steps:**

1. **Development**: Code changes with automatic version bumps on commit (via pre-commit hook)
1. **CI Pipeline**: Tests, linting, security scans run automatically on push
1. **Release Creation**: Draft release created automatically on push to main (if all checks pass)
1. **Manual Review**: Review draft release, add additional notes if needed
1. **Publish**: Manually publish release when ready (draft releases allow review before publishing)

**Example Release Creation Script (in CI workflow):**

```python
# Extract version from __init__.py
import re
with open('project_name/__init__.py', 'r') as f:
    content = f.read()
match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
version = match.group(1)

# Check if release exists
tag = f"v{version}"
# ... check via GitHub API ...

# Get commits since last release
# ... git log since last tag ...

# Create draft release
# ... GitHub API call ...
```

### Release Toolkit Components

1. **Version Extraction Script**: Python script in CI workflow that reads version from source files
1. **Release Check Script**: Checks if release with version tag already exists via GitHub API
1. **Changelog Generator**: Creates release notes from git log (commit messages since last release)
1. **Release Creator**: Creates draft release via GitHub API with changelog

**Benefits:**

- No manual version management
- Consistent versioning across all files
- Automatic changelog generation
- Draft releases allow review before publishing
- Reduces human error in release process

## 6. Development Workflow

### Local Development Setup

1. **Virtual Environment**: Always use venv for isolation

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Linux/macOS
   # or
   venv\Scripts\activate  # Windows
   ```

1. **Dependencies**: Install from `requirements-dev.txt`

   ```bash
   pip install --upgrade pip
   pip install -r requirements-dev.txt
   ```

1. **Pre-commit Hooks**: Ensure hooks are executable

   ```bash
   chmod +x .git/hooks/pre-commit
   ```

1. **Testing**: Run `pytest` before committing

   ```bash
   pytest
   # or with coverage
   pytest --cov=project_name --cov-report=html
   ```

1. **Formatting**: Pre-commit hook handles formatting automatically, but you can run manually:

   ```bash
   black project_name/ tests/
   ruff check --fix project_name/ tests/
   ```

### Docker Development

1. **Build**: `make docker-build` or `docker-compose build`
1. **Run**: `make docker-up` or `docker-compose up -d`
1. **Logs**: `make docker-logs` or `docker-compose logs -f`
1. **Clean**: `make docker-clean` to remove old artifacts
1. **Deploy**: `make docker-deploy` for full clean rebuild

**Recommended Approach:**

- Use **local development** for day-to-day coding and testing
- Use **Docker** to verify the containerized deployment works correctly
- Both approaches are supported and can be used interchangeably

### Makefile Commands

Standard commands to include in Makefile:

```makefile
.PHONY: help install install-dev test lint format clean docker-build docker-up docker-down docker-logs docker-shell docker-clean docker-rebuild docker-deploy

help:
 @echo "Available commands:"
 @echo "  make install       - Install production dependencies"
 @echo "  make install-dev   - Install development dependencies"
 @echo "  make test          - Run tests"
 @echo "  make lint          - Run linters"
 @echo "  make format        - Format code"
 @echo "  make clean         - Clean build artifacts"
 @echo "  make docker-build  - Build Docker image"
 @echo "  make docker-up     - Start container"
 @echo "  make docker-down   - Stop container"
 @echo "  make docker-logs   - View container logs"
 @echo "  make docker-deploy - Full deployment: clean, rebuild, and start"

install:
 pip install -r requirements.txt

install-dev:
 pip install -r requirements-dev.txt

test:
 pytest

lint:
 ruff check project_name/
 mypy project_name/

format:
 black project_name/
 ruff check --fix project_name/

clean:
 find . -type d -name __pycache__ -exec rm -r {} +
 find . -type f -name "*.pyc" -delete
 rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov

# Docker commands
docker-build:
 docker-compose build

docker-up:
 docker-compose up -d

docker-down:
 docker-compose down

docker-logs:
 docker-compose logs -f

docker-deploy: docker-clean docker-rebuild docker-up

docker-clean:
 docker-compose down
 docker rmi project_name-project-name 2>/dev/null || true

docker-rebuild:
 docker-compose build --no-cache
```

## 7. Project Configuration

### pyproject.toml Structure

The `pyproject.toml` file serves as the central configuration for Python projects:

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "project-name"
version = "0.1.0"
description = "Project description"
readme = "README.md"
requires-python = ">=3.9"
license = {text = "MIT"}
authors = [
    {name = "Project Contributors"}
]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

dependencies = [
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    # ... other dependencies
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
    "mypy>=1.0.0",
    # ... other dev dependencies
]

[tool.setuptools.packages.find]
where = ["."]
include = ["project_name*"]

[tool.black]
line-length = 100
target-version = ['py39']

[tool.ruff]
line-length = 100
target-version = "py39"

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--tb=short",
]
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "slow: Slow running tests",
    "benchmark: Performance benchmark tests",
    "database: Tests that require database access",
]
```

### Docker Configuration

**Multi-stage Build**: Separate build and runtime stages to minimize final image size.

**Example Dockerfile:**

```dockerfile
# Build stage
FROM python:3.12-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r -g 1001 appuser && useradd -r -g appuser -u 1001 appuser

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Create directories with proper permissions
RUN mkdir -p /config /logs /data && \
    chown -R appuser:appuser /app /config /logs /data

ENV PATH=/home/appuser/.local/bin:$PATH

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Default command
CMD ["python", "-m", "uvicorn", "project_name.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Key Docker Best Practices:**

- **Non-root User**: Run as dedicated user (UID 1001) for security
- **Health Checks**: Built-in health monitoring for container orchestration
- **Volume Mounts**: Persistent data, logs, and config via volumes
- **Security**: Minimal base image, no unnecessary packages
- **Layer Caching**: Order Dockerfile commands to maximize cache hits

## 8. Implementation Timeline

### Phase 1: Foundation (Week 1)

**Goals**: Set up basic project structure and documentation

- \[ \] Set up repository structure (directories, basic files)
- \[ \] Create basic documentation (README.md, QUICK_START.md)
- \[ \] Configure pyproject.toml with project metadata
- \[ \] Set up basic test structure (tests/ directory, conftest.py)
- \[ \] Create .gitignore file
- \[ \] Add LICENSE file

**Deliverables**: Working project skeleton with basic docs

### Phase 2: CI/CD Setup (Week 1-2)

**Goals**: Establish automated testing and quality checks

- \[ \] Create GitHub Actions workflow file (`.github/workflows/ci.yml`)
- \[ \] Set up test job with matrix strategy (multiple Python versions)
- \[ \] Add linting and formatting checks (ruff, black, mypy)
- \[ \] Configure Docker build job
- \[ \] Test CI pipeline with sample commits

**Deliverables**: Working CI pipeline that runs on every push/PR

### Phase 3: Testing Infrastructure (Week 2)

**Goals**: Establish comprehensive testing framework

- \[ \] Set up pytest configuration in pyproject.toml
- \[ \] Create test fixtures (database, test client, sample data)
- \[ \] Write initial unit tests for core functionality
- \[ \] Write initial integration tests for API endpoints
- \[ \] Configure coverage reporting
- \[ \] Document testing practices in tests/README.md

**Deliverables**: Test suite with good coverage and clear documentation

### Phase 4: Release Toolkit (Week 2-3)

**Goals**: Automate version management and releases

- \[ \] Create pre-commit hook for version management
- \[ \] Test version incrementing across all files
- \[ \] Set up automated release workflow in GitHub Actions
- \[ \] Test release creation process
- \[ \] Document release process

**Deliverables**: Automated versioning and release creation

### Phase 5: Documentation (Week 3)

**Goals**: Complete comprehensive documentation

- \[ \] Complete ARCHITECTURE.md with all sections
- \[ \] Write HOW_TO_USE.md user guide
- \[ \] Create tests/README.md testing guide
- \[ \] Review and refine all documentation
- \[ \] Add diagrams and visual aids where helpful
- \[ \] Cross-reference between documents

**Deliverables**: Complete documentation suite

### Phase 6: Security & Quality (Week 3-4)

**Goals**: Establish security scanning and quality gates

- \[ \] Add security scanning to CI (Bandit, TruffleHog)
- \[ \] Set up dependency vulnerability checking (pip-audit)
- \[ \] Configure secret scanning
- \[ \] Review and harden security practices
- \[ \] Document security considerations

**Deliverables**: Security scanning integrated into CI pipeline

## 9. Checklist for New Projects

Use this checklist when setting up a new project to ensure nothing is missed:

### Initial Setup

- \[ \] Repository created with appropriate name
- \[ \] README.md with project overview
- \[ \] .gitignore configured for Python/project type
- \[ \] License file added (MIT, Apache, etc.)
- \[ \] Basic project structure created (directories)
- \[ \] Initial commit made

### Documentation

- \[ \] README.md complete with all sections
- \[ \] ARCHITECTURE.md created (if applicable)
- \[ \] HOW_TO_USE.md created (for user-facing projects)
- \[ \] QUICK_START.md created
- \[ \] tests/README.md created
- \[ \] All documentation cross-referenced

### CI/CD

- \[ \] GitHub Actions workflow created (`.github/workflows/ci.yml`)
- \[ \] Test job configured with matrix strategy
- \[ \] Lint job configured (ruff, black, mypy)
- \[ \] Docker build job configured (if using Docker)
- \[ \] Security scanning configured (Bandit, TruffleHog)
- \[ \] Dependency vulnerability checking configured
- \[ \] Release workflow configured (if applicable)
- \[ \] CI pipeline tested and working

### Development Tools

- \[ \] Pre-commit hook installed and tested
- \[ \] Makefile with common commands created
- \[ \] pyproject.toml configured with all tool settings
- \[ \] requirements.txt created with production dependencies
- \[ \] requirements-dev.txt created with development dependencies
- \[ \] Virtual environment setup documented

### Testing

- \[ \] Test structure created (unit/, integration/)
- \[ \] conftest.py with fixtures created
- \[ \] Initial tests written for core functionality
- \[ \] Coverage reporting configured
- \[ \] Test markers defined and documented
- \[ \] Tests passing in CI

### Release Management

- \[ \] Version management strategy defined
- \[ \] Pre-commit hook for version bumping created
- \[ \] Version stored in all required locations
- \[ \] Automated release workflow tested
- \[ \] Release notes template created
- \[ \] Release process documented

### Docker (if applicable)

- \[ \] Dockerfile created with multi-stage build
- \[ \] docker-compose.yml for development
- \[ \] docker-compose.prod.yml for production
- \[ \] Non-root user configured
- \[ \] Health checks configured
- \[ \] Volume mounts documented
- \[ \] Docker build tested in CI

### Security

- \[ \] Secrets management strategy defined
- \[ \] No secrets committed to repository
- \[ \] Security scanning in CI
- \[ \] Dependency vulnerability checking
- \[ \] Security best practices documented

## 10. Key Takeaways

1. **Documentation First**: Good documentation enables collaboration and onboarding. Invest time in clear, comprehensive docs from the start.

1. **Automation**: Automate repetitive tasks (versioning, formatting, releases) to reduce errors and save time.

1. **Testing Early**: Set up testing infrastructure from the start. It's much harder to add tests later.

1. **CI/CD Pipeline**: A comprehensive pipeline catches issues early and ensures code quality. Don't skip this step.

1. **Security**: Build security scanning into the workflow from day one. It's easier than retrofitting later.

1. **Consistency**: Use tools (black, ruff) to maintain code consistency automatically. Let tools enforce standards.

1. **Docker**: Containerization ensures consistent environments across development, testing, and production.

1. **Version Management**: Automated versioning reduces errors and ensures consistency across all files.

1. **Separation of Concerns**: Clear separation between API, services, and data layers makes code maintainable.

1. **Iterative Improvement**: Start with the basics and add complexity as needed. Don't try to implement everything at once.

This guide provides a complete blueprint for setting up production-ready GitHub repositories following industry best practices and the patterns established in successful projects. Use it as a reference when starting new projects, and adapt it to your specific needs.
