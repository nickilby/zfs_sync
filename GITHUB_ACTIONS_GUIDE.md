# GitHub Actions CI/CD Guide

This document outlines the CI/CD principles and patterns used in this repository's GitHub Actions workflows. Use this guide to implement similar automation in new projects.

## Table of Contents

1. [Core Principles](#core-principles)
2. [Workflow Structure](#workflow-structure)
3. [Job Breakdown](#job-breakdown)
4. [Configuration Patterns](#configuration-patterns)
5. [Best Practices](#best-practices)
6. [Template Workflow](#template-workflow)
7. [Customization Guide](#customization-guide)

---

## Core Principles

### 1. **Comprehensive Testing**
- Test across multiple Python versions to ensure compatibility
- Generate coverage reports to track test quality
- Run tests in parallel for faster feedback

### 2. **Code Quality Enforcement**
- Automated linting and formatting checks
- Type checking for type safety
- Fail fast on quality issues

### 3. **Security First**
- Scan code for security vulnerabilities
- Check dependencies for known CVEs
- Detect secrets in code before merge

### 4. **Containerization Validation**
- Build and test Docker images
- Verify container functionality
- Test health endpoints

### 5. **Automated Release Management**
- Extract version from source files
- Generate changelogs from commits
- Create draft releases automatically

### 6. **Parallel Execution**
- Run independent jobs in parallel
- Use job dependencies for sequential steps
- Optimize workflow runtime

---

## Workflow Structure

### Trigger Configuration

```yaml
on:
  pull_request:
    branches: [ main, master, develop ]
  push:
    branches: [ main, master, develop ]
  workflow_dispatch:  # Manual trigger
```

**Principles:**
- Run on PRs to catch issues before merge
- Run on pushes to main branches for continuous integration
- Allow manual dispatch for testing/debugging

### Job Organization

Jobs are organized by function and run in parallel where possible:

1. **test** - Multi-version testing with coverage
2. **lint** - Code quality checks
3. **docker-build** - Container validation (depends on test)
4. **security-scan** - Security analysis
5. **dependency-check** - Vulnerability scanning
6. **benchmark** - Performance testing (optional, conditional)
7. **create-release** - Release automation (depends on all, main branch only)

---

## Job Breakdown

### 1. Test Job

**Purpose:** Run tests across multiple Python versions with coverage reporting

**Key Features:**
- Matrix strategy for multiple Python versions
- Coverage reporting (XML, HTML, terminal)
- Codecov integration
- Artifact upload for HTML reports

**Configuration Pattern:**
```yaml
test:
  name: Test Python ${{ matrix.python-version }}
  runs-on: ubuntu-latest
  strategy:
    matrix:
      python-version: ["3.9", "3.10", "3.11", "3.12"]
    fail-fast: false  # Continue testing other versions if one fails

  steps:
    - uses: actions/checkout@v4
    
    - uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
        cache: 'pip'  # Cache pip dependencies
    
    - run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install -r requirements-dev.txt
    
    - run: |
        pytest --cov=<project_name> \
               --cov-report=xml \
               --cov-report=term-missing \
               --cov-report=html \
               -v
    
    # Upload coverage only from one Python version to avoid duplicates
    - uses: codecov/codecov-action@v3
      if: matrix.python-version == '3.11'
      with:
        file: ./coverage.xml
        fail_ci_if_error: false
    
    - uses: actions/upload-artifact@v4
      if: matrix.python-version == '3.11'
      with:
        name: coverage-report
        path: htmlcov/
        retention-days: 30
```

**Customization Points:**
- Adjust Python versions in matrix
- Change coverage upload condition
- Modify pytest arguments
- Update project name in coverage path

---

### 2. Lint Job

**Purpose:** Enforce code quality through linting, type checking, and formatting

**Key Features:**
- Ruff for fast linting
- MyPy for type checking
- Black for format verification
- Fail on formatting issues

**Configuration Pattern:**
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
    
    - run: |
        python -m pip install --upgrade pip
        pip install -r requirements-dev.txt
    
    - run: ruff check <project_name>/ tests/
    
    - run: mypy <project_name>/
      continue-on-error: true  # Allow gradual type adoption
    
    - run: black --check <project_name>/ tests/
```

**Customization Points:**
- Adjust Python version
- Enable/disable continue-on-error for mypy
- Add additional linting tools
- Configure tool-specific options

---

### 3. Docker Build Job

**Purpose:** Validate Docker image builds and functionality

**Key Features:**
- Build Docker image with caching
- Test image import/functionality
- Health check endpoint testing
- GitHub Actions cache for Docker layers

**Configuration Pattern:**
```yaml
docker-build:
  name: Docker Build Test
  runs-on: ubuntu-latest
  needs: [test]  # Only run if tests pass

  steps:
    - uses: actions/checkout@v4
    
    - uses: docker/setup-buildx-action@v3
    
    - uses: docker/build-push-action@v5
      with:
        context: .
        file: ./Dockerfile
        push: false
        load: true
        tags: <project-name>:test
        cache-from: type=gha  # Use GitHub Actions cache
        cache-to: type=gha,mode=max
    
    - run: |
        docker run --rm <project-name>:test \
          python -c "import <project_name>; print('Import successful')"
    
    - run: |
        docker run -d --name <project-name>-test -p 8000:8000 <project-name>:test
        sleep 10
        for i in {1..10}; do
          if curl -f http://localhost:8000/api/v1/health; then
            echo "Health check passed"
            break
          fi
          echo "Attempt $i failed, retrying..."
          sleep 2
        done
        docker stop <project-name>-test || true
        docker rm <project-name>-test || true
```

**Customization Points:**
- Adjust health check endpoint path
- Modify health check retry logic
- Change port mappings
- Add additional container tests

---

### 4. Security Scan Job

**Purpose:** Identify security vulnerabilities and secrets in code

**Key Features:**
- Bandit for Python security scanning
- TruffleHog for secret detection
- Artifact upload for reports
- Conditional secret scanning based on event type

**Configuration Pattern:**
```yaml
security-scan:
  name: Security Scanning
  runs-on: ubuntu-latest

  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # Full history for secret scanning
    
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: 'pip'
    
    - run: |
        python -m pip install --upgrade pip
        pip install -r requirements-dev.txt
    
    - run: |
        bandit -r <project_name>/ -f json -o bandit-report.json || true
        bandit -r <project_name>/ -ll
      continue-on-error: true
    
    - uses: actions/upload-artifact@v4
      if: always()
      with:
        name: bandit-security-report
        path: bandit-report.json
        retention-days: 30
    
    # Secret scanning for PRs (compare against base)
    - uses: trufflesecurity/trufflehog@main
      if: github.event_name == 'pull_request'
      with:
        path: ./
        base: ${{ github.event.pull_request.base.sha }}
        head: ${{ github.event.pull_request.head.sha }}
      continue-on-error: true
    
    # Secret scanning for pushes (scan entire repo)
    - uses: trufflesecurity/trufflehog@main
      if: github.event_name == 'push'
      with:
        path: ./
      continue-on-error: true
```

**Customization Points:**
- Adjust Bandit severity levels
- Configure TruffleHog patterns
- Add additional security tools
- Change artifact retention period

---

### 5. Dependency Check Job

**Purpose:** Audit dependencies for known vulnerabilities

**Key Features:**
- Separate audits for production and development dependencies
- JSON report generation
- Critical/High severity failure
- Artifact upload for reports

**Configuration Pattern:**
```yaml
dependency-check:
  name: Dependency Vulnerability Check
  runs-on: ubuntu-latest

  steps:
    - uses: actions/checkout@v4
    
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: 'pip'
    
    - run: |
        python -m pip install --upgrade pip
        pip install pip-audit
    
    - run: |
        pip-audit --requirement requirements.txt \
                  --format json \
                  --output pip-audit-prod.json || true
        pip-audit --requirement requirements.txt
      continue-on-error: true
    
    - run: |
        pip-audit --requirement requirements-dev.txt \
                  --format json \
                  --output pip-audit-dev.json || true
        pip-audit --requirement requirements-dev.txt
      continue-on-error: true
    
    - uses: actions/upload-artifact@v4
      if: always()
      with:
        name: dependency-audit-reports
        path: |
          pip-audit-prod.json
          pip-audit-dev.json
        retention-days: 30
    
    - run: |
        pip-audit --requirement requirements.txt --desc > audit-output.txt 2>&1 || true
        if grep -i "CRITICAL\|HIGH" audit-output.txt; then
          echo "Critical or High severity vulnerabilities found!"
          cat audit-output.txt
          exit 1
        else
          echo "No critical or high severity vulnerabilities found"
        fi
```

**Customization Points:**
- Adjust severity thresholds
- Add additional requirement files
- Configure audit verbosity
- Modify failure conditions

---

### 6. Benchmark Job (Optional)

**Purpose:** Track performance metrics over time

**Key Features:**
- Conditional execution (PRs and manual dispatch)
- JSON result storage
- GitHub step summary display
- Artifact upload for historical tracking

**Configuration Pattern:**
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
        cache: 'pip'
    
    - run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install -r requirements-dev.txt
    
    - run: |
        pytest --benchmark-only \
               --benchmark-json=benchmark-results.json \
               -m benchmark || echo "No benchmark tests found"
      continue-on-error: true
    
    - uses: actions/upload-artifact@v4
      if: always()
      with:
        name: benchmark-results
        path: benchmark-results.json
        retention-days: 90
    
    - run: |
        if [ -f benchmark-results.json ]; then
          echo "## Benchmark Results" >> $GITHUB_STEP_SUMMARY
          echo "\`\`\`json" >> $GITHUB_STEP_SUMMARY
          cat benchmark-results.json | head -50 >> $GITHUB_STEP_SUMMARY
          echo "\`\`\`" >> $GITHUB_STEP_SUMMARY
        else
          echo "No benchmark tests found or benchmarks failed" >> $GITHUB_STEP_SUMMARY
        fi
```

**Customization Points:**
- Adjust execution conditions
- Modify pytest benchmark arguments
- Change artifact retention
- Add benchmark comparison logic

---

### 7. Create Release Job

**Purpose:** Automatically create draft releases on main branch pushes

**Key Features:**
- Version extraction from source files
- Duplicate release detection
- Changelog generation from commits
- Draft release creation

**Configuration Pattern:**
```yaml
create-release:
  name: Create Draft Release
  runs-on: ubuntu-latest
  needs: [test, lint, docker-build, security-scan, dependency-check]
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  permissions:
    contents: write  # Required to create releases

  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # Full history for changelog
    
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    
    - run: |
        python -m pip install --upgrade pip
        pip install requests
    
    # Extract version from source file
    - name: Extract version
      id: extract_version
      run: |
        python << 'EOF'
        import re
        import os
        import sys
        
        # Option 1: From __init__.py
        with open('<project_name>/__init__.py', 'r') as f:
            content = f.read()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        
        # Option 2: From pyproject.toml (alternative)
        # import tomllib  # Python 3.11+
        # with open('pyproject.toml', 'rb') as f:
        #     data = tomllib.load(f)
        #     version = data['project']['version']
        
        if match:
            version = match.group(1)
            output_file = os.environ.get('GITHUB_OUTPUT')
            if output_file:
                with open(output_file, 'a') as f:
                    f.write(f"VERSION={version}\n")
            print(f"Extracted version: {version}")
        else:
            print("Error: Could not extract version")
            sys.exit(1)
        EOF
    
    # Check if release already exists
    - name: Check if release exists
      id: check_release
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        VERSION: ${{ steps.extract_version.outputs.VERSION }}
      run: |
        python << 'EOF'
        import os
        import sys
        import requests
        
        version = os.environ.get('VERSION')
        token = os.environ.get('GITHUB_TOKEN')
        repo = os.environ.get('GITHUB_REPOSITORY')
        tag = f"v{version}"
        
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        response = requests.get(url, headers=headers)
        output_file = os.environ.get('GITHUB_OUTPUT')
        
        if response.status_code == 200:
            print(f"Release with tag {tag} already exists")
            if output_file:
                with open(output_file, 'a') as f:
                    f.write("RELEASE_EXISTS=true\n")
        elif response.status_code == 404:
            print(f"Release with tag {tag} does not exist")
            if output_file:
                with open(output_file, 'a') as f:
                    f.write("RELEASE_EXISTS=false\n")
        else:
            print(f"Error: {response.status_code}")
            sys.exit(1)
        EOF
    
    # Generate changelog from commits
    - name: Get commit messages since last release
      id: get_commits
      if: steps.check_release.outputs.RELEASE_EXISTS == 'false'
      run: |
        python << 'EOF'
        import os
        import subprocess
        
        result = subprocess.run(
            ['git', 'tag', '--list', 'v*', '--sort=-version:refname'],
            capture_output=True,
            text=True
        )
        
        tags = [t for t in result.stdout.strip().split('\n') if t]
        
        if tags:
            last_tag = tags[0]
            result = subprocess.run(
                ['git', 'log', f'{last_tag}..HEAD', '--pretty=format:%s', '--no-merges'],
                capture_output=True,
                text=True
            )
            commits = [c for c in result.stdout.strip().split('\n') if c]
            base_message = f"## Changes since {last_tag}\n\n"
        else:
            result = subprocess.run(
                ['git', 'log', '--pretty=format:%s', '--no-merges'],
                capture_output=True,
                text=True
            )
            commits = [c for c in result.stdout.strip().split('\n') if c]
            base_message = "## Initial Release\n\n"
        
        if commits:
            commit_list = "\n".join([f"- {commit}" for commit in commits])
            release_body = base_message + commit_list
        else:
            release_body = base_message + "No commits found."
        
        with open('release_body.txt', 'w', encoding='utf-8') as f:
            f.write(release_body)
        
        output_file = os.environ.get('GITHUB_OUTPUT')
        if output_file:
            with open(output_file, 'a') as f:
                f.write(f"COMMIT_COUNT={len(commits)}\n")
        
        print(f"Found {len(commits)} commits since last release")
        EOF
    
    # Create the draft release
    - name: Create draft release
      if: steps.check_release.outputs.RELEASE_EXISTS == 'false'
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        VERSION: ${{ steps.extract_version.outputs.VERSION }}
      run: |
        python << 'EOF'
        import os
        import sys
        import requests
        import json
        
        version = os.environ.get('VERSION')
        token = os.environ.get('GITHUB_TOKEN')
        repo = os.environ.get('GITHUB_REPOSITORY')
        sha = os.environ.get('GITHUB_SHA')
        tag = f"v{version}"
        
        try:
            with open('release_body.txt', 'r', encoding='utf-8') as f:
                release_body = f.read()
        except FileNotFoundError:
            release_body = f"Automated draft release for version {version}"
        
        url = f"https://api.github.com/repos/{repo}/releases"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        data = {
            "tag_name": tag,
            "name": f"Release {tag}",
            "body": release_body,
            "draft": True,
            "prerelease": False,
            "target_commitish": sha
        }
        
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 201:
            release_data = response.json()
            print(f"Successfully created draft release: {release_data['html_url']}")
        else:
            print(f"Error: {response.status_code} - {response.text}")
            sys.exit(1)
        EOF
```

**Customization Points:**
- Change version extraction method (__init__.py vs pyproject.toml)
- Modify changelog format
- Adjust release naming convention
- Add release notes template

---

## Configuration Patterns

### Caching Strategy

**Principle:** Cache dependencies and build artifacts to speed up workflows

```yaml
# Python pip cache
- uses: actions/setup-python@v5
  with:
    cache: 'pip'

# Docker layer cache
- uses: docker/build-push-action@v5
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

### Conditional Execution

**Principle:** Run jobs/steps only when appropriate

```yaml
# Job-level condition
if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'

# Step-level condition
if: matrix.python-version == '3.11'
if: always()  # Run even if previous step failed
if: steps.check_release.outputs.RELEASE_EXISTS == 'false'
```

### Job Dependencies

**Principle:** Ensure proper execution order

```yaml
# Sequential execution
needs: [test]

# Multiple dependencies
needs: [test, lint, docker-build, security-scan, dependency-check]
```

### Artifact Management

**Principle:** Store reports and results for later analysis

```yaml
- uses: actions/upload-artifact@v4
  with:
    name: <artifact-name>
    path: <path-to-files>
    retention-days: 30  # Adjust based on needs
```

### Error Handling

**Principle:** Fail fast on critical issues, continue on warnings

```yaml
# Fail on error (default)
- run: black --check .

# Continue on error (warnings)
- run: mypy .
  continue-on-error: true

# Conditional failure
- run: |
    if grep -i "CRITICAL" report.txt; then
      exit 1
    fi
```

---

## Best Practices

### 1. **Use Latest Action Versions**
- Regularly update action versions (e.g., `@v4`, `@v5`)
- Pin to major versions for stability
- Check for security updates

### 2. **Optimize Workflow Speed**
- Run independent jobs in parallel
- Use caching for dependencies
- Set `fail-fast: false` in matrix to test all versions
- Use conditional execution to skip unnecessary steps

### 3. **Security Considerations**
- Use `GITHUB_TOKEN` for repository operations
- Never hardcode secrets
- Use `continue-on-error: true` for non-blocking security scans
- Scan for secrets in PRs

### 4. **Clear Job and Step Names**
- Use descriptive names: `Test Python 3.11` vs `test`
- Include context in step names
- Use consistent naming conventions

### 5. **Artifact Management**
- Set appropriate retention periods
- Upload artifacts conditionally (`if: always()` for reports)
- Use meaningful artifact names

### 6. **Error Reporting**
- Use `continue-on-error: true` for non-critical checks
- Upload reports even on failure
- Provide clear error messages

### 7. **Version Management**
- Extract version from source files (single source of truth)
- Check for duplicate releases
- Generate meaningful changelogs

### 8. **Resource Efficiency**
- Use `fetch-depth: 0` only when needed (full git history)
- Cache dependencies appropriately
- Clean up temporary resources

---

## Template Workflow

Here's a complete template workflow file you can adapt:

```yaml
name: CI

on:
  pull_request:
    branches: [ main, master, develop ]
  push:
    branches: [ main, master, develop ]
  workflow_dispatch:

jobs:
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
      - run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      - run: |
          pytest --cov=<project_name> \
                 --cov-report=xml \
                 --cov-report=html \
                 -v
      - uses: codecov/codecov-action@v3
        if: matrix.python-version == '3.11'
        with:
          file: ./coverage.xml
      - uses: actions/upload-artifact@v4
        if: matrix.python-version == '3.11'
        with:
          name: coverage-report
          path: htmlcov/
          retention-days: 30

  lint:
    name: Lint and Format Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: 'pip'
      - run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt
      - run: ruff check <project_name>/ tests/
      - run: mypy <project_name>/
        continue-on-error: true
      - run: black --check <project_name>/ tests/

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
          tags: <project-name>:test
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - run: |
          docker run --rm <project-name>:test \
            python -c "import <project_name>; print('OK')"

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
          cache: 'pip'
      - run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt
      - run: |
          bandit -r <project_name>/ -f json -o bandit-report.json || true
          bandit -r <project_name>/ -ll
        continue-on-error: true
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: bandit-security-report
          path: bandit-report.json
          retention-days: 30
      - uses: trufflesecurity/trufflehog@main
        if: github.event_name == 'pull_request'
        with:
          path: ./
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
        continue-on-error: true

  dependency-check:
    name: Dependency Vulnerability Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: 'pip'
      - run: |
          python -m pip install --upgrade pip
          pip install pip-audit
      - run: |
          pip-audit --requirement requirements.txt || true
        continue-on-error: true
      - run: |
          pip-audit --requirement requirements.txt --desc > audit-output.txt 2>&1 || true
          if grep -i "CRITICAL\|HIGH" audit-output.txt; then
            echo "Critical vulnerabilities found!"
            exit 1
          fi
```

---

## Customization Guide

### For New Projects

1. **Replace Placeholders:**
   - `<project_name>` → Your Python package name
   - `<project-name>` → Your Docker image name (kebab-case)

2. **Adjust Python Versions:**
   - Update matrix versions based on your `requires-python` in `pyproject.toml`
   - Update single-version references if needed

3. **Modify Test Configuration:**
   - Update pytest arguments
   - Adjust coverage paths
   - Change coverage upload conditions

4. **Customize Linting:**
   - Add/remove linting tools
   - Configure tool-specific options
   - Adjust continue-on-error settings

5. **Docker Configuration:**
   - Update image tags
   - Modify health check endpoints
   - Adjust port mappings
   - Add container-specific tests

6. **Security Tools:**
   - Configure Bandit severity levels
   - Adjust TruffleHog patterns
   - Add additional security scanners

7. **Release Automation:**
   - Choose version extraction method (__init__.py or pyproject.toml)
   - Customize changelog format
   - Adjust release naming

8. **Branch Names:**
   - Update trigger branches
   - Modify release branch condition

### Optional Enhancements

- **Add deployment jobs** for staging/production
- **Add notification steps** (Slack, email, etc.)
- **Add performance regression detection**
- **Add dependency update automation** (Dependabot)
- **Add code quality badges** (Codecov, etc.)
- **Add matrix testing for OS** (ubuntu, windows, macos)

---

## Summary

This CI/CD workflow follows these key principles:

1. ✅ **Comprehensive Testing** - Multi-version, coverage reporting
2. ✅ **Quality Enforcement** - Linting, type checking, formatting
3. ✅ **Security First** - Code scanning, dependency auditing, secret detection
4. ✅ **Container Validation** - Build and test Docker images
5. ✅ **Automated Releases** - Version extraction, changelog generation
6. ✅ **Parallel Execution** - Optimized workflow runtime
7. ✅ **Error Handling** - Appropriate failure modes
8. ✅ **Artifact Management** - Report storage and retention

Adapt these patterns to your project's specific needs while maintaining these core principles.
