#!/bin/bash

# Kokoro TTS — Comprehensive QA Check
# Runs all quality checks before pushing code
# Usage: ./qa_check.sh

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

TARGET="src"
ERRORS=0

print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

run_check() {
    local tool_name=$1
    shift
    local cmd=("$@")

    if command_exists "${cmd[0]}"; then
        echo -e "${YELLOW}Running $tool_name...${NC}"
        if "${cmd[@]}"; then
            echo -e "${GREEN}$tool_name passed${NC}"
            return 0
        else
            echo -e "${RED}$tool_name failed${NC}"
            ((ERRORS++))
        fi
    else
        echo -e "${RED}$tool_name not installed (pip install ${cmd[0]})${NC}"
        ((ERRORS++))
    fi
}

echo -e "\n${BLUE}Kokoro TTS — Comprehensive QA Check${NC}"
echo -e "${CYAN}Target: $TARGET${NC}\n"

# Phase 1: Formatting & Linting
print_header "PHASE 1: FORMATTING & LINTING"
run_check "Ruff Format" ruff format "$TARGET"
run_check "Ruff Lint" ruff check "$TARGET" --fix

# Phase 2: Type Checking
print_header "PHASE 2: TYPE CHECKING"
run_check "Pyright" pyright "$TARGET"

# Phase 3: Security Scanning
print_header "PHASE 3: SECURITY SCANNING"
run_check "Bandit" bandit -r "$TARGET" -ll -f screen

# Phase 4: Code Quality Metrics
print_header "PHASE 4: CODE QUALITY METRICS"

if command_exists radon; then
    echo -e "${YELLOW}Running Radon (Complexity)...${NC}"
    echo -e "${CYAN}Cyclomatic Complexity:${NC}"
    radon cc "$TARGET" -a -nb || true
    echo -e "\n${CYAN}Maintainability Index:${NC}"
    radon mi "$TARGET" -nb || true
    echo -e "${GREEN}Radon analysis complete${NC}"
else
    echo -e "${RED}Radon not installed${NC}"
    ((ERRORS++))
fi

run_check "Vulture (Dead Code)" vulture "$TARGET" --min-confidence 80
run_check "Interrogate (Docstrings)" interrogate "$TARGET" -v

# Phase 5: Testing
print_header "PHASE 5: TESTING"

if command_exists pytest; then
    echo -e "${YELLOW}Running pytest...${NC}"
    if pytest --cov="$TARGET" --cov-report=term-missing -v; then
        echo -e "${GREEN}All tests passed${NC}"
    else
        echo -e "${RED}Tests failed${NC}"
        ((ERRORS++))
    fi
else
    echo -e "${RED}pytest not installed${NC}"
    ((ERRORS++))
fi

# Summary
print_header "SUMMARY"

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}All checks passed${NC}"
    exit 0
else
    echo -e "${RED}$ERRORS check(s) failed — fix before pushing${NC}"
    exit 1
fi
