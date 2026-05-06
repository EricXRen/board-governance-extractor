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

uv run gov-extract extract \
  --input data/2025-lbg-annual-report.pdf \
  --company "Lloyds Banking Group" \
  --year 2025 \
  --page-hint 60 \
  --provider openai \
  --model deepseek-v4-flash \
  --output-dir ./outputs

uv run gov-extract extract \
  --input data/2025-lbg-annual-report.pdf \
  --company "Lloyds Banking Group" \
  --year 2025 \
  --output-dir ./outputs
  
 
 


uv run gov-extract extract \
  --input data/AstraZeneca_AR_2025.pdf \
  --company "AstraZeneca" \
  --year 2025 \
  --output-dir ./outputs


  # uv run gov-extract extract --input <pdf> --company "..." --year 2025 \
  #   --provider azure_openai --model gpt-4o --output-dir ./outputs


uv run gov-extract evaluate \
    --extracted outputs/LloydsBankingGroup_2025_Board_Governance_deepseek.json \
    --ground-truth outputs/LloydsBankingGroup_2025_Board_Governance_openai.json \
    --output-dir ./outputs


#   Optional flags:
#   - --fail-on-regression — exit with code 1 if any gate threshold is breached (useful in CI)
#   - --config path/to/config.yaml — use a custom config

# To generate the evaluation schema (if you want to customize it or add more fields), edit src/gov_extract/models/generate_schema.py and then run:
uv run src/gov_extract/models/generate_schema.py