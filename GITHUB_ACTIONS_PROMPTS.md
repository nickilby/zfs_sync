# GitHub Actions CI/CD Setup Prompts

This document provides a set of prompts and questions to guide you through setting up a comprehensive CI/CD pipeline for any new project using GitHub Actions. Use these prompts with an AI assistant or as a checklist for manual setup.

---

## Quick Start Prompt

Use this prompt to get started:

```
I need to set up a GitHub Actions CI/CD workflow for my project. Please help me create a comprehensive workflow that includes:

1. Multi-version testing with coverage reporting
2. Code quality checks (linting, type checking, formatting)
3. Security scanning (code and dependencies)
4. Docker build and validation (if applicable)
5. Automated release creation (if applicable)

My project details:
- Project name: [YOUR_PROJECT_NAME]
- Language/Runtime: [Python/Node.js/Go/etc.]
- Package name: [YOUR_PACKAGE_NAME]
- Main branches: [main/master/develop]
- Python versions to test: [3.9, 3.10, 3.11, 3.12] (if applicable)
- Has Dockerfile: [yes/no]
- Version location: [__init__.py/pyproject.toml/package.json/etc.]
```

---

## Detailed Setup Prompts

### Phase 1: Project Discovery

Use these prompts to gather project information:

#### Prompt 1.1: Project Basics
```
What is the basic information about your project?
- Project name (for display): 
- Package/module name (for imports): 
- Primary programming language: 
- Framework/library (if applicable): 
- Main branches to protect: 
```

#### Prompt 1.2: Testing Configuration
```
What testing setup do you need?
- Test framework: [pytest/jest/mocha/etc.]
- Test command: [pytest/jest test/etc.]
- Coverage tool: [pytest-cov/nyc/etc.]
- Coverage threshold: [80%/90%/none]
- Test markers/tags: [unit/integration/benchmark/etc.]
- Test directories: [tests/__tests__/spec/etc.]
```

#### Prompt 1.3: Python-Specific (if applicable)
```
If using Python, what are your requirements?
- Minimum Python version: 
- Python versions to test: [3.9, 3.10, 3.11, 3.12]
- Requirements file: [requirements.txt/pyproject.toml]
- Dev requirements file: [requirements-dev.txt]
- Package structure: [single module/package with __init__.py]
```

#### Prompt 1.4: Code Quality Tools
```
What code quality tools do you use?
- Linter: [ruff/flake8/eslint/etc.]
- Formatter: [black/prettier/gofmt/etc.]
- Type checker: [mypy/typescript/etc.]
- Additional tools: [isort/sort-imports/etc.]
```

#### Prompt 1.5: Container Configuration (if applicable)
```
If using Docker, what are your requirements?
- Dockerfile path: [./Dockerfile]
- Image name: 
- Health check endpoint: [/health/api/v1/health/etc.]
- Health check port: [8000/3000/etc.]
- Additional container tests needed: [yes/no]
```

#### Prompt 1.6: Security Requirements
```
What security scanning do you need?
- Code security scanner: [bandit/semgrep/etc.]
- Dependency scanner: [pip-audit/npm audit/snyk/etc.]
- Secret detection: [trufflehog/gitleaks/etc.]
- Security report format: [JSON/HTML/both]
```

#### Prompt 1.7: Release Management
```
Do you need automated releases?
- Create releases automatically: [yes/no]
- Version source: [__init__.py/pyproject.toml/package.json/etc.]
- Release type: [draft/automatic]
- Changelog generation: [from commits/custom template]
- Release branches: [main/master]
```

---

### Phase 2: Workflow Generation Prompts

Use these prompts to generate specific workflow components:

#### Prompt 2.1: Complete Workflow Generation
```
Generate a complete GitHub Actions workflow file (.github/workflows/ci.yml) for my project with these specifications:

Project: [PROJECT_NAME]
Package: [PACKAGE_NAME]
Language: [LANGUAGE]
Python versions: [VERSIONS] (if applicable)
Branches: [BRANCHES]
Test command: [TEST_CMD]
Coverage command: [COV_CMD]
Linter: [LINTER]
Formatter: [FORMATTER]
Type checker: [TYPE_CHECKER]
Docker: [YES/NO]
Security tools: [TOOLS]
Release automation: [YES/NO]
Version location: [LOCATION]

Include:
1. Workflow triggers (PR, push, manual)
2. Test job with matrix strategy
3. Lint job with all quality checks
4. Security scan job
5. Dependency check job
6. Docker build job (if applicable)
7. Release job (if applicable)
8. Proper job dependencies
9. Artifact uploads
10. Caching for dependencies
```

#### Prompt 2.2: Test Job Generation
```
Create a GitHub Actions test job that:
- Tests across Python versions: [VERSIONS]
- Runs command: [TEST_COMMAND]
- Generates coverage in formats: [XML, HTML, terminal]
- Uploads coverage to Codecov (if configured)
- Uploads HTML coverage report as artifact
- Uses pip caching
- Fails fast: [true/false]

Package name: [PACKAGE_NAME]
Requirements files: [FILES]
```

#### Prompt 2.3: Lint Job Generation
```
Create a GitHub Actions lint job that:
- Runs linter: [LINTER] with command: [LINT_CMD]
- Runs type checker: [TYPE_CHECKER] with command: [TYPE_CMD]
- Checks formatting: [FORMATTER] with command: [FORMAT_CMD]
- Uses pip caching
- Fails on formatting errors
- Continues on type errors (for gradual adoption)

Directories to check: [DIRS]
```

#### Prompt 2.4: Docker Job Generation
```
Create a GitHub Actions Docker build job that:
- Builds Docker image from: [DOCKERFILE_PATH]
- Tags image as: [IMAGE_NAME]:test
- Uses GitHub Actions cache for layers
- Tests image import/functionality
- Tests health endpoint at: [HEALTH_ENDPOINT]
- Runs on port: [PORT]
- Retries health check: [N] times with [N] second delays
- Depends on test job passing

Image name: [IMAGE_NAME]
```

#### Prompt 2.5: Security Scan Job Generation
```
Create a GitHub Actions security scan job that:
- Runs code security scanner: [SCANNER] with command: [SCAN_CMD]
- Scans for secrets using: [SECRET_SCANNER]
- Generates JSON report: [REPORT_FILE]
- Uploads security reports as artifacts
- Continues on error (non-blocking)
- Scans full git history for secrets

Project directory: [PROJECT_DIR]
```

#### Prompt 2.6: Dependency Check Job Generation
```
Create a GitHub Actions dependency check job that:
- Audits production dependencies: [REQ_FILE]
- Audits development dependencies: [DEV_REQ_FILE]
- Generates JSON reports
- Fails on CRITICAL or HIGH severity vulnerabilities
- Uploads audit reports as artifacts
- Uses tool: [AUDIT_TOOL]

Tool command: [AUDIT_CMD]
```

#### Prompt 2.7: Release Job Generation
```
Create a GitHub Actions release job that:
- Extracts version from: [VERSION_SOURCE]
- Checks if release already exists
- Generates changelog from commits since last release
- Creates draft release with tag: v[VERSION]
- Only runs on pushes to: [BRANCH]
- Requires all other jobs to pass
- Uses GitHub API with GITHUB_TOKEN

Version extraction method: [METHOD]
Changelog format: [FORMAT]
```

---

### Phase 3: Customization Prompts

Use these prompts to customize and enhance your workflow:

#### Prompt 3.1: Add Conditional Jobs
```
Add conditional execution to my GitHub Actions workflow:
- Job: [JOB_NAME]
- Condition: [ONLY_ON_PRS/ONLY_ON_PUSH/ONLY_MANUAL/etc.]
- Additional conditions: [SPECIFIC_BRANCHES/etc.]

Current workflow file: [FILE_PATH]
```

#### Prompt 3.2: Add Matrix Strategy
```
Add a matrix strategy to my test job for:
- Operating systems: [ubuntu-latest/windows-latest/macos-latest]
- Python versions: [VERSIONS]
- Framework versions: [VERSIONS]
- Other dimensions: [SPECIFY]

Job name: [JOB_NAME]
```

#### Prompt 3.3: Add Artifact Uploads
```
Add artifact upload steps to my workflow:
- Artifact name: [NAME]
- Files/directories: [PATHS]
- Retention days: [DAYS]
- Condition: [always/on_success/etc.]

Job: [JOB_NAME]
```

#### Prompt 3.4: Add Notifications
```
Add notification steps to my workflow:
- Notification type: [Slack/Email/Discord/etc.]
- Webhook URL: [URL] (or secret name)
- Trigger conditions: [on_failure/on_success/always]
- Message format: [CUSTOM_FORMAT]

Jobs to notify: [JOB_NAMES]
```

#### Prompt 3.5: Add Deployment Jobs
```
Add deployment jobs to my workflow:
- Environment: [staging/production]
- Deployment method: [Docker/Serverless/VM/etc.]
- Deployment script: [SCRIPT_PATH]
- Required approvals: [yes/no]
- Trigger conditions: [on_tag/on_main_branch/etc.]

Deployment target: [TARGET]
```

#### Prompt 3.6: Add Performance Benchmarks
```
Add a benchmark job to my workflow:
- Benchmark framework: [pytest-benchmark/benchmark.js/etc.]
- Benchmark command: [CMD]
- Output format: [JSON/CSV]
- Compare against baseline: [yes/no]
- Upload results: [yes/no]
- Display in PR comments: [yes/no]

Test markers: [MARKERS]
```

---

### Phase 4: Optimization Prompts

Use these prompts to optimize your workflow:

#### Prompt 4.1: Add Caching
```
Optimize my GitHub Actions workflow with caching:
- Cache type: [pip/npm/docker/etc.]
- Cache key: [SPECIFY]
- Cache paths: [PATHS]
- Restore keys: [KEYS]

Jobs to optimize: [JOB_NAMES]
```

#### Prompt 4.2: Parallelize Jobs
```
Review my workflow and suggest parallelization opportunities:
- Current workflow: [FILE_PATH]
- Identify independent jobs that can run in parallel
- Suggest job dependency optimizations
- Recommend fail-fast settings
```

#### Prompt 4.3: Reduce Workflow Time
```
Analyze my workflow for time optimization:
- Current workflow: [FILE_PATH]
- Identify slow steps
- Suggest caching strategies
- Recommend conditional execution
- Propose job splitting or merging
```

#### Prompt 4.4: Add Workflow Status Badges
```
Generate markdown badges for my GitHub Actions workflows:
- Workflow file: [FILE_PATH]
- Badge style: [flat/flat-square/plastic/etc.]
- Include status for: [all_jobs/specific_jobs]
- Branch: [BRANCH]
```

---

### Phase 5: Troubleshooting Prompts

Use these prompts when debugging issues:

#### Prompt 5.1: Debug Workflow Failure
```
My GitHub Actions workflow is failing. Help me debug:
- Workflow file: [FILE_PATH]
- Failing job: [JOB_NAME]
- Error message: [ERROR]
- Step that fails: [STEP_NAME]
- Logs: [RELEVANT_LOG_EXCERPT]
```

#### Prompt 5.2: Fix Permission Issues
```
Fix permission issues in my workflow:
- Error: [PERMISSION_ERROR]
- Job: [JOB_NAME]
- Required permissions: [contents:write/packages:write/etc.]
- Current permissions block: [CURRENT_PERMISSIONS]
```

#### Prompt 5.3: Resolve Dependency Conflicts
```
Resolve dependency installation issues:
- Language: [LANGUAGE]
- Error: [ERROR_MESSAGE]
- Requirements file: [FILE]
- Lock file: [FILE] (if applicable)
- Cache issues: [yes/no]
```

#### Prompt 5.4: Fix Secret Detection False Positives
```
Configure secret detection to reduce false positives:
- Tool: [trufflehog/gitleaks/etc.]
- False positive patterns: [PATTERNS]
- Configuration file: [CONFIG_FILE]
- Exclude paths: [PATHS]
```

---

## Complete Example Prompts

### Example 1: Python Package with Docker
```
Create a complete GitHub Actions CI/CD workflow for a Python package with these requirements:

Project: my-python-app
Package: my_python_app
Python versions: 3.9, 3.10, 3.11, 3.12
Branches: main, develop
Test command: pytest --cov=my_python_app --cov-report=xml --cov-report=html -v
Linter: ruff check my_python_app/ tests/
Formatter: black --check my_python_app/ tests/
Type checker: mypy my_python_app/
Docker: Yes (Dockerfile at ./Dockerfile, image name: my-python-app, health endpoint: /api/v1/health on port 8000)
Security: bandit for code, pip-audit for dependencies, trufflehog for secrets
Releases: Yes (version from my_python_app/__init__.py, draft releases on main branch)

Include all jobs with proper dependencies, caching, and artifact uploads.
```

### Example 2: Node.js Application
```
Create a complete GitHub Actions CI/CD workflow for a Node.js application:

Project: my-node-app
Package: my-node-app
Node versions: 18.x, 20.x
Branches: main, master
Test command: npm test
Coverage: npm run test:coverage (generates coverage/ directory)
Linter: eslint src/ tests/
Formatter: prettier --check src/ tests/
Type checker: tsc --noEmit
Docker: No
Security: npm audit for dependencies, gitleaks for secrets
Releases: Yes (version from package.json, automatic releases on main branch)

Include all jobs with proper dependencies, caching, and artifact uploads.
```

### Example 3: Go Application
```
Create a complete GitHub Actions CI/CD workflow for a Go application:

Project: my-go-app
Package: github.com/user/my-go-app
Go versions: 1.20, 1.21, 1.22
Branches: main
Test command: go test -v -coverprofile=coverage.out ./...
Coverage: go tool cover -html=coverage.out -o coverage.html
Linter: golangci-lint run
Formatter: gofmt -d .
Docker: Yes (Dockerfile at ./Dockerfile, image name: my-go-app, health endpoint: /health on port 8080)
Security: gosec for code, go list -json -m all | nancy sleuth for dependencies
Releases: Yes (version from VERSION file, draft releases on main branch)

Include all jobs with proper dependencies, caching, and artifact uploads.
```

---

## Prompt Templates for Common Scenarios

### Template 1: Minimal CI Setup
```
Create a minimal GitHub Actions CI workflow that:
- Runs tests on pull requests and pushes to main
- Tests on [LANGUAGE] version [VERSION]
- Runs command: [TEST_CMD]
- Fails if tests fail

Project: [PROJECT_NAME]
```

### Template 2: Full CI/CD with Deployment
```
Create a complete CI/CD pipeline that:
- Runs all quality checks (test, lint, format, type check)
- Builds and tests Docker image
- Runs security scans
- Deploys to staging on merge to develop
- Deploys to production on tag creation
- Creates releases automatically

Project: [PROJECT_NAME]
Deployment method: [METHOD]
Environments: [ENVIRONMENTS]
```

### Template 3: Library Package CI
```
Create a CI workflow for a library package that:
- Tests across multiple versions: [VERSIONS]
- Tests on multiple OS: [OS_LIST]
- Generates coverage reports
- Checks code quality
- Publishes to package registry on release tag
- Does NOT include Docker or deployment

Project: [PROJECT_NAME]
Package registry: [PYPI/NPM/MAVEN/etc.]
```

---

## Checklist for Manual Setup

Use this checklist if setting up manually:

### Initial Setup
- [ ] Create `.github/workflows/` directory
- [ ] Decide on workflow file name (e.g., `ci.yml`, `cd.yml`)
- [ ] Determine trigger branches
- [ ] List required jobs

### Test Job
- [ ] Define Python/Node/Go versions to test
- [ ] Set up matrix strategy
- [ ] Configure test command
- [ ] Set up coverage reporting
- [ ] Configure Codecov (if using)
- [ ] Set up artifact uploads

### Lint Job
- [ ] Choose linter tool
- [ ] Choose formatter tool
- [ ] Choose type checker (if applicable)
- [ ] Configure tool commands
- [ ] Set continue-on-error flags

### Security Job
- [ ] Choose code security scanner
- [ ] Choose dependency scanner
- [ ] Choose secret detection tool
- [ ] Configure report generation
- [ ] Set up artifact uploads

### Docker Job (if applicable)
- [ ] Configure Docker build
- [ ] Set up layer caching
- [ ] Configure health check
- [ ] Set job dependencies

### Release Job (if applicable)
- [ ] Determine version source
- [ ] Create version extraction script
- [ ] Configure changelog generation
- [ ] Set up release creation
- [ ] Configure permissions

### Optimization
- [ ] Add dependency caching
- [ ] Add Docker layer caching
- [ ] Review job dependencies
- [ ] Add conditional execution
- [ ] Set appropriate retention periods

### Final Steps
- [ ] Test workflow on a branch
- [ ] Verify all jobs run successfully
- [ ] Check artifact uploads
- [ ] Test release creation (if applicable)
- [ ] Add workflow status badges to README

---

## Quick Reference: Key Decisions

When setting up CI/CD, make these decisions:

1. **Triggers**: Which events should trigger the workflow?
   - Pull requests
   - Pushes to specific branches
   - Manual dispatch
   - Tags/releases

2. **Testing Strategy**: How comprehensive should testing be?
   - Single version vs. matrix
   - Coverage requirements
   - Test types (unit, integration, e2e)

3. **Quality Gates**: What must pass before merge?
   - Tests
   - Linting
   - Formatting
   - Type checking
   - Security scans

4. **Deployment**: Do you need automated deployment?
   - Staging environment
   - Production environment
   - Manual approval gates

5. **Releases**: How should releases be managed?
   - Automatic vs. manual
   - Draft vs. published
   - Changelog generation

6. **Notifications**: Who needs to know about failures?
   - Slack
   - Email
   - Teams
   - Custom webhooks

---

## Next Steps

After generating your workflow:

1. **Review** the generated workflow file
2. **Customize** placeholders and paths
3. **Test** on a feature branch
4. **Iterate** based on results
5. **Document** any project-specific configurations
6. **Monitor** workflow performance and optimize

---

## Tips for Using These Prompts

1. **Start Simple**: Begin with basic CI, then add complexity
2. **Be Specific**: Include exact commands, paths, and versions
3. **Iterate**: Generate, test, refine, repeat
4. **Copy Patterns**: Use working examples as templates
5. **Ask for Explanations**: Request explanations of complex configurations
6. **Version Control**: Commit workflow changes incrementally

---

## Additional Resources

When using these prompts, you may also want to reference:
- GitHub Actions documentation
- Language-specific CI/CD examples
- Security scanning tool documentation
- Docker best practices
- Release management strategies
