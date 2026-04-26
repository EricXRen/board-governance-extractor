#!/usr/bin/env bash
# Example: extract Lloyds Banking Group FY2025 governance data
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

uv run gov-extract extract \
  --input "$REPO_ROOT/examples/2025-lbg-annual-report.pdf" \
  --company "Lloyds Banking Group" \
  --year 2025 \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --output-dir "$REPO_ROOT/outputs"
