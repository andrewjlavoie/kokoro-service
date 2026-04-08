# Kokoro TTS — QA Commands

.PHONY: help
help:  ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: install-dev
install-dev:  ## Install QA tools
	pip install -r requirements-dev.txt

.PHONY: qa
qa:  ## Run comprehensive QA checks (before pushing)
	@chmod +x qa_check.sh
	@./qa_check.sh

.PHONY: qa-quick
qa-quick:  ## Run quick QA checks (daily development)
	@chmod +x qa_quick.sh
	@./qa_quick.sh

.PHONY: format
format:  ## Auto-format code with ruff
	ruff format src
	ruff check src --fix

.PHONY: lint
lint:  ## Run linting only
	ruff check src

.PHONY: type
type:  ## Run type checking only
	pyright src

.PHONY: security
security:  ## Run security scan
	bandit -r src -ll

.PHONY: test
test:  ## Run tests with coverage
	pytest --cov=src --cov-report=term-missing -v

.PHONY: test-quick
test-quick:  ## Run tests without coverage
	pytest -v

.PHONY: complexity
complexity:  ## Show code complexity metrics
	radon cc src -a -nb
	@echo "\n--- Maintainability Index ---"
	radon mi src -nb

.PHONY: dead-code
dead-code:  ## Find unused code
	vulture src --min-confidence 80

.PHONY: docstrings
docstrings:  ## Check docstring coverage
	interrogate src -v

.PHONY: clean
clean:  ## Clean QA artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
