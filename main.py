"""
Prompt-driven CI/CD agent for Databricks and ADF.
Entry point: CLI and programmatic API.
"""

import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv
import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from parser import PromptParser
from patcher import FilePatcher
from validator import Validator
from git_ops import GitOps

load_dotenv()
console = Console()
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("agent")


def run_agent(platform: str, file_path: str, prompt: str, dry_run: bool = False) -> dict:
    """
    Core agent pipeline:
      1. Parse intent from prompt
      2. Fetch current file from repo
      3. Generate patched content via LLM
      4. Validate (bundle validate / ARM validate)
      5. Commit, push, raise PR
    Returns a result dict with branch, pr_url, diff summary.
    """
    console.rule("[bold]Prompt-driven CI/CD Agent")

    # ── Step 1: Parse ────────────────────────────────────────
    console.print("\n[bold cyan]Step 1/5[/] Parsing intent from prompt...")
    parser = PromptParser()
    intent = parser.parse(platform=platform, file_path=file_path, prompt=prompt)
    console.print(f"  Platform  : [cyan]{intent['platform']}[/]")
    console.print(f"  Operation : [cyan]{intent['operation']}[/]")
    console.print(f"  File      : [cyan]{intent['file_path']}[/]")

    # ── Step 2: Fetch current file ───────────────────────────
    console.print("\n[bold cyan]Step 2/5[/] Fetching current file from repo...")
    git = GitOps(
        token=os.environ["GITHUB_TOKEN"],
        repo_name=os.environ["GITHUB_REPO"],
        base_branch=os.getenv("GITHUB_BASE_BRANCH", "main"),
    )
    current_content, current_sha = git.get_file(intent["file_path"])
    console.print(f"  Fetched {len(current_content)} bytes from [cyan]{intent['file_path']}[/]")

    # ── Step 3: Generate patch ───────────────────────────────
    console.print("\n[bold cyan]Step 3/5[/] Generating modified content via LLM...")
    patcher = FilePatcher(api_key=os.environ["ANTHROPIC_API_KEY"])
    modified_content, diff_summary, commit_msg, pr_description = patcher.patch(
        platform=intent["platform"],
        file_path=intent["file_path"],
        current_content=current_content,
        prompt=prompt,
        operation=intent["operation"],
    )

    console.print(Panel(
        Syntax(diff_summary, "diff", theme="ansi_dark", line_numbers=False),
        title="Generated diff",
        border_style="cyan",
    ))

    # ── Step 4: Validate ─────────────────────────────────────
    console.print("\n[bold cyan]Step 4/5[/] Validating changes...")
    validator = Validator(
        databricks_host=os.getenv("DATABRICKS_HOST"),
        databricks_token=os.getenv("DATABRICKS_TOKEN"),
        azure_subscription_id=os.getenv("AZURE_SUBSCRIPTION_ID"),
        azure_resource_group=os.getenv("AZURE_RESOURCE_GROUP"),
        azure_tenant_id=os.getenv("AZURE_TENANT_ID"),
        azure_client_id=os.getenv("AZURE_CLIENT_ID"),
        azure_client_secret=os.getenv("AZURE_CLIENT_SECRET"),
        adf_factory_name=os.getenv("ADF_FACTORY_NAME"),
    )
    validation_result = validator.validate(
        platform=intent["platform"],
        file_path=intent["file_path"],
        content=modified_content,
    )
    if not validation_result["passed"]:
        console.print(f"[bold red]Validation failed:[/] {validation_result['error']}")
        sys.exit(1)
    console.print(f"  [green]✓[/] {validation_result['message']}")

    if dry_run or os.getenv("DRY_RUN", "false").lower() == "true":
        console.print("\n[yellow]DRY RUN — skipping commit and PR.[/]")
        return {"dry_run": True, "diff": diff_summary, "commit_msg": commit_msg}

    # ── Step 5: Commit, push, PR ─────────────────────────────
    console.print("\n[bold cyan]Step 5/5[/] Committing, pushing, and raising PR...")
    branch_name = f"feat/prompt-{_short_hash(prompt)}-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"

    result = git.commit_and_pr(
        branch_name=branch_name,
        file_path=intent["file_path"],
        new_content=modified_content,
        current_sha=current_sha,
        commit_message=commit_msg,
        pr_title=commit_msg,
        pr_body=pr_description,
        reviewers=os.getenv("GITHUB_REVIEWERS", "").split(","),
        labels=os.getenv("GITHUB_LABELS", "auto-generated").split(","),
    )

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[green]✓ Branch[/]", result["branch"])
    table.add_row("[green]✓ Commit[/]", result["commit_sha"][:10])
    table.add_row("[green]✓ PR[/]", result["pr_url"])
    console.print(Panel(table, title="Done", border_style="green"))

    return result


def _short_hash(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()[:8]


# ── CLI ──────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--platform", "-p",
    type=click.Choice(["databricks", "databricks-job", "adf-pipeline", "adf-dataset", "adf-linked"]),
    required=True, help="Target platform")
@click.option("--file", "-f", "file_path", required=True,
    help="Relative path in repo, e.g. databricks/notebooks/silver/silver_orders.py")
@click.option("--prompt", "-m", required=True,
    help="Natural language description of the change")
@click.option("--dry-run", is_flag=True, default=False,
    help="Parse and generate only — do not commit or raise PR")
def cli(platform, file_path, prompt, dry_run):
    """Prompt-driven CI/CD: modify Databricks or ADF resources via natural language."""
    run_agent(platform=platform, file_path=file_path, prompt=prompt, dry_run=dry_run)


if __name__ == "__main__":
    cli()
