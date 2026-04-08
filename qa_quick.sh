#!/bin/bash

# Kokoro TTS — Quick QA Check
# Essential checks only (format, lint, type, security)
# Usage: ./qa_quick.sh

set -e

TARGET="src"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}Quick QA Check: $TARGET${NC}\n"

echo "1/4 Formatting..."
ruff format "$TARGET"

echo "2/4 Linting..."
ruff check "$TARGET" --fix

echo "3/4 Type checking..."
pyright "$TARGET" || echo -e "${YELLOW}Type warnings (non-blocking)${NC}"

echo "4/4 Security scanning..."
bandit -r "$TARGET" -ll -q || echo -e "${YELLOW}Security warnings (non-blocking)${NC}"

echo -e "\n${GREEN}Quick checks passed${NC}"
echo -e "${CYAN}Run './qa_check.sh' for comprehensive checks before pushing${NC}"
