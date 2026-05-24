"""
Sends the current file content + prompt to Claude and returns:
  - modified file content
  - unified diff summary
  - commit message
  - PR description (Markdown)
"""

import difflib
import json
import logging
import os
import re
import textwrap
from datetime import datetime

import anthropic

log = logging.getLogger(__name__)

PATCH_SYSTEM_PROMPTS = {
    "databricks": """You are a senior Azure Data Engineer. You will receive a Databricks Python notebook
and a change request. Modify the notebook to fulfil the request.

Rules:
- Preserve all existing imports and Spark session setup unless explicitly asked to change them
- Follow PEP 8 and Databricks notebook conventions (# COMMAND ---------- cell separators)
- Use Delta Lake best practices (merge instead of overwrite where appropriate)
- Add a short inline comment for every new block of logic
- Keep data quality checks (not-null assertions, row count logging)
- Return ONLY the full modified file content. No markdown fences, no explanation.""",

    "databricks-job": """You are a senior Azure Data Engineer. You will receive a Databricks Asset Bundle
job YAML and a change request. Modify the YAML to fulfil the request.

Rules:
- Preserve existing cluster policies and access modes
- Validate task dependencies remain acyclic
- Keep existing library references unless asked to change them
- Return ONLY the full modified YAML. No markdown fences.""",

    "adf-pipeline": """You are a senior Azure Data Factory engineer. You will receive an ADF pipeline JSON
and a change request. Modify the JSON to fulfil the request.

Rules:
- Preserve all existing activities unless explicitly asked to remove them
- Maintain dependency chain integrity (dependsOn must be consistent)
- Use ADF best practices: parameterise hardcoded values, use Key Vault references for secrets
- Keep annotations and descriptions
- Return ONLY the full modified JSON. No markdown fences.""",

    "adf-dataset": """You are a senior Azure Data Factory engineer. Modify the ADF dataset JSON as requested.
Return ONLY the full modified JSON. No markdown fences.""",

    "adf-linked": """You are a senior Azure Data Factory engineer. Modify the ADF linked service JSON as requested.
Never hardcode secrets — use Azure Key Vault references.
Return ONLY the full modified JSON. No markdown fences.""",
}

COMMIT_MSG_SYSTEM = """Generate a conventional commit message for the following change.
Format: <type>(<scope>): <short description>
Types: feat, fix, refactor, chore, docs
Keep under 72 characters.
Respond with ONLY the commit message line, nothing else."""

PR_BODY_SYSTEM = """Generate a professional GitHub pull request description in Markdown for the following change.
Include sections: ## Summary, ## Changes, ## Files changed, ## Validation, ## Rollback plan.
Keep it concise and factual."""


class FilePatcher:
    def __init__(self, api_key: str | None = None):
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    def patch(
        self,
        platform: str,
        file_path: str,
        current_content: str,
        prompt: str,
        operation: str = "modify",
    ) -> tuple[str, str, str, str]:
        """
        Returns (modified_content, diff_summary, commit_message, pr_description).
        """
        if operation == "create":
            modified = self._create_new(platform, file_path, prompt)
        else:
            modified = self._modify_existing(platform, file_path, current_content, prompt)

        diff = self._unified_diff(current_content, modified, file_path)
        commit_msg = self._generate_commit_msg(platform, file_path, prompt)
        pr_body = self._generate_pr_body(platform, file_path, prompt, diff, commit_msg)

        log.info("Patch generated — %d lines changed", diff.count("\n"))
        return modified, diff, commit_msg, pr_body

    def _modify_existing(self, platform: str, file_path: str, current: str, prompt: str) -> str:
        system = PATCH_SYSTEM_PROMPTS.get(platform, PATCH_SYSTEM_PROMPTS["databricks"])
        user = (
            f"File: {file_path}\n\n"
            f"--- CURRENT CONTENT ---\n{current}\n"
            f"--- END CONTENT ---\n\n"
            f"Change requested: {prompt}"
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return self._strip_fences(response.content[0].text)

    def _create_new(self, platform: str, file_path: str, prompt: str) -> str:
        system = PATCH_SYSTEM_PROMPTS.get(platform, PATCH_SYSTEM_PROMPTS["databricks"])
        user = (
            f"Create a new file: {file_path}\n\n"
            f"Requirements: {prompt}\n\n"
            f"Use Databricks / ADF best practices. Add clear section comments."
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return self._strip_fences(response.content[0].text)

    def _generate_commit_msg(self, platform: str, file_path: str, prompt: str) -> str:
        scope = file_path.split("/")[-1].replace(".py", "").replace(".json", "").replace(".yml", "")
        user = f"Platform: {platform}\nFile: {file_path}\nChange: {prompt}"
        response = self._client.messages.create(
            model=self._model,
            max_tokens=100,
            system=COMMIT_MSG_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text.strip()

    def _generate_pr_body(
        self, platform: str, file_path: str, prompt: str, diff: str, commit_msg: str
    ) -> str:
        user = (
            f"Platform: {platform}\n"
            f"File: {file_path}\n"
            f"Prompt: {prompt}\n"
            f"Commit message: {commit_msg}\n\n"
            f"Diff summary (first 60 lines):\n{chr(10).join(diff.splitlines()[:60])}"
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=PR_BODY_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        body = response.content[0].text.strip()
        body += (
            f"\n\n---\n*Auto-generated by prompt-cicd agent · "
            f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*\n"
            f"*Original prompt: `{prompt[:200]}`*"
        )
        return body

    @staticmethod
    def _unified_diff(original: str, modified: str, filename: str) -> str:
        orig_lines = original.splitlines(keepends=True)
        mod_lines = modified.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines, mod_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
        )
        return "".join(diff)

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        text = re.sub(r"\n?```$", "", text)
        return text.strip()
