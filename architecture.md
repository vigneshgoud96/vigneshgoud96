# Architecture & runbook

## System overview

```
User prompt
    │
    ▼
PromptParser (Claude)
    │  Classifies: platform, operation, risk
    ▼
FilePatcher (Claude)
    │  Reads current file → generates targeted patch → diff
    ▼
Validator
    │  Python syntax / YAML parse / JSON schema / ARM validate / bundle validate
    ▼
GitOps (GitHub API)
    │  Creates branch → commits file → raises PR
    ▼
GitHub Actions CI
    │  Lint → test → validate → deploy (staging → prod with approval gate)
    ▼
Databricks / ADF
```

## Supported platforms

| Platform key | Target | Validation | Deploy mechanism |
|---|---|---|---|
| `databricks` | Python notebook `.py` | Python syntax + bundle validate | `databricks bundle deploy` |
| `databricks-job` | Job YAML | YAML parse + bundle validate | `databricks bundle deploy` |
| `adf-pipeline` | Pipeline JSON | JSON schema + ARM validate | `az datafactory pipeline create` |
| `adf-dataset` | Dataset JSON | JSON schema + ARM validate | `az datafactory dataset create` |
| `adf-linked` | Linked service JSON | JSON schema + ARM validate | `az datafactory linked-service create` |

## GitHub Secrets required

Set these in GitHub → Settings → Secrets and variables → Actions:

```
ANTHROPIC_API_KEY         Claude API key
GH_PAT                    GitHub PAT (repo + PR scope)
DATABRICKS_HOST           Workspace URL
DATABRICKS_TOKEN          Databricks PAT
DATABRICKS_HOST_STAGING   Staging workspace URL
DATABRICKS_TOKEN_STAGING  Staging PAT
DATABRICKS_HOST_PROD      Production workspace URL
DATABRICKS_TOKEN_PROD     Production PAT
AZURE_CLIENT_ID           Service principal app ID
AZURE_TENANT_ID           Azure AD tenant
AZURE_SUBSCRIPTION_ID     Subscription
AZURE_RESOURCE_GROUP_STAGING
AZURE_RESOURCE_GROUP_PROD
ADF_FACTORY_NAME_STAGING
ADF_FACTORY_NAME_PROD
```

## GitHub Environments

Create two environments in GitHub → Settings → Environments:

- **staging** — auto-deploy on merge to main
- **production** — requires manual approval from a designated reviewer

## Rollback procedure

### Databricks
```bash
# List recent bundle deploys
databricks bundle run --target prod --list

# Roll back: redeploy previous git sha
git checkout <previous-sha>
cd databricks && databricks bundle deploy --target prod
```

### ADF pipeline
```bash
# ADF maintains a version history per pipeline
az datafactory pipeline show \
  --factory-name <adf-name> \
  --resource-group <rg> \
  --name pl_orders_medallion

# Restore from git: redeploy previous JSON
az datafactory pipeline create \
  --factory-name <adf-name> \
  --resource-group <rg> \
  --name pl_orders_medallion \
  --pipeline @adf/pipeline/pl_orders_medallion.json
```

## Adding a new target resource

1. Add a system prompt to `agent/patcher.py` → `PATCH_SYSTEM_PROMPTS`
2. Add a validator in `agent/validator.py` → `Validator.validate()`
3. Add the platform key to `agent/parser.py` → `PLATFORM_PATHS`
4. Add a deploy step to the appropriate GitHub Actions workflow
5. Write a unit test in `tests/test_agent.py`

## Common prompts reference

```bash
# Databricks — add logic
python agent/main.py -p databricks \
  -f databricks/notebooks/silver/silver_orders.py \
  -m "Add a data quality check: assert no nulls in customer_id column"

# Databricks — change cluster config
python agent/main.py -p databricks-job \
  -f databricks/jobs/databricks.yml \
  -m "Increase max_workers to 16 for the gold_aggregate task"

# ADF — add activity
python agent/main.py -p adf-pipeline \
  -f adf/pipeline/pl_orders_medallion.json \
  -m "Add a validation activity before CopyOrdersToLanding that checks source row count > 0"

# ADF — update schedule
python agent/main.py -p adf-pipeline \
  -f adf/pipeline/pl_orders_medallion.json \
  -m "Change the trigger schedule to run at 2 AM UTC instead of 6 AM"

# Dry run (no commit)
python agent/main.py -p databricks \
  -f databricks/notebooks/gold/gold_revenue_agg.py \
  -m "Add a breakdown by product category to the gold aggregation" \
  --dry-run
```
