#!/bin/bash
# CI script for code quality checks

set -euo pipefail

SCRIPTDIR="$(realpath "$(dirname "${0}")")"
REPODIR="$(realpath "${SCRIPTDIR}/..")"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 {format|linter|type|shellcheck|test|all}"
    echo ""
    echo "Commands:"
    echo "  format     - Check Python code formatting with ruff"
    echo "  linter     - Lint Python code with ruff"
    echo "  type       - Check type annotations with ty"
    echo "  shellcheck - Check shell scripts with shellcheck"
    echo "  test       - Run tests with coverage report"
    echo "  all        - Run all checks (format, linter, type, shellcheck, test)"
    exit 1
}

# Check functions
check_format() {
    echo -e "${GREEN}Checking code formatting...${NC}"
    ruff format --check --diff .
    echo -e "${GREEN}✓ Formatting check passed${NC}"
}

check_linter() {
    echo -e "${GREEN}Running ruff check...${NC}"
    ruff check .
    echo -e "${GREEN}✓ Linting complete${NC}"
    if command -v pylint >/dev/null 2>&1
    then
        echo -e "${GREEN}Running pylint...${NC}"
        pylint .
        echo -e "${GREEN}✓ Linting with pylint completed${NC}"
    else
        echo -e "${YELLOW}SKIP: 'pylint' is not available.${NC}"
    fi
}

check_type() {
    echo -e "${GREEN}Running ty type checker...${NC}"
    ty check .
    echo -e "${GREEN}✓ Type checking complete${NC}"
}

check_shellcheck() {
    echo -e "${GREEN}Running shellcheck...${NC}"
    find . -type f -name '*.sh' -exec shellcheck -x -a -o all -e SC2292 -e SC2310 -e SC2311 {} +
    echo -e "${GREEN}✓ Shellcheck passed${NC}"
}

check_test() {
    echo -e "${GREEN}Running tests with coverage...${NC}"
    PYTHONPATH=${REPODIR} pytest --cov=ipaclient --cov-report=term-missing --cov-report=html
    echo -e "${GREEN}✓ Tests complete (coverage report: htmlcov/index.html)${NC}"
}

# Check argument
if [ $# -ne 1 ]; then
    usage
fi

case "$1" in
    format)
        check_format
        ;;
    linter)
        check_linter
        ;;
    type)
        check_type
        ;;
    shellcheck)
        check_shellcheck
        ;;
    test)
        check_test
        ;;
    all)
        echo -e "${YELLOW}Running all checks...${NC}"
        echo ""

        check_format
        echo ""

        check_linter
        echo ""

        check_type
        echo ""

        check_shellcheck
        echo ""

        check_test
        echo ""

        echo -e "${GREEN}✓ All checks passed${NC}"
        ;;
    *)
        echo -e "${RED}Error: Unknown command '$1'${NC}"
        usage
        ;;
esac
