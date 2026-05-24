# Prompt-Driven CI/CD for Databricks & ADF

Auto-modify Databricks notebooks and ADF pipelines via natural language prompts, with auto commit, push, and PR.

## Project structure

```
prompt-cicd/
├── agent/                  # Core AI agent
│   ├── main.py             # Entry point (CLI + API)
│   ├── parser.py           # Prompt intent parser
│   ├── patcher.py          # File patching logic
│   ├── validator.py        # Pre-commit validation
│   └── git_ops.py          # GitHub API automation
├── databricks/
│   ├── notebooks/          # Versioned notebooks (bronze/silver/gold)
│   └── jobs/               # Databricks Asset Bundle job configs
├── adf/
│   ├── pipeline/           # ADF pipeline JSON
│   ├── dataset/            # ADF dataset JSON
│   └── linkedService/      # ADF linked service JSON
├── cicd/
│   ├── deploy_databricks.yml   # GitHub Actions - Databricks
│   ├── deploy_adf.yml          # GitHub Actions - ADF
│   └── pr_validation.yml       # GitHub Actions - PR checks
├── tests/                  # Unit + integration tests
├── scripts/                # Bootstrap & utility scripts
└── docs/                   # Architecture & runbook
```

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables (copy from .env.example)
cp .env.example .env && nano .env

# 3. Run the agent
python agent/main.py \
  --platform databricks \
  --file notebooks/silver/silver_orders.py \
  --prompt "Add deduplication on order_id before writing to silver layer"
```

## Environment variables required

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key for the AI agent |
| `GITHUB_TOKEN` | PAT with repo + PR permissions |
| `GITHUB_REPO` | e.g. `org/prompt-cicd` |
| `DATABRICKS_HOST` | e.g. `https://adb-xxx.azuredatabricks.net` |
| `DATABRICKS_TOKEN` | Databricks PAT |
| `AZURE_SUBSCRIPTION_ID` | For ADF ARM validation |
| `AZURE_RESOURCE_GROUP` | Resource group containing ADF |
| `ADF_FACTORY_NAME` | ADF instance name |
| `AZURE_TENANT_ID` | Azure AD tenant |
| `AZURE_CLIENT_ID` | Service principal app ID |
| `AZURE_CLIENT_SECRET` | Service principal secret |

## Supported operations

- **Modify** existing Databricks notebook (`.py`, `.ipynb`)
- **Modify** existing ADF pipeline / dataset / linked service JSON
- **Create** new notebook with medallion layer scaffold
- **Create** new ADF pipeline from description
- **Validate** before commit (bundle validate + ARM validate)
- **Auto PR** with generated description and reviewer tags
