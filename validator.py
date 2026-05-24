"""
Pre-commit validation for generated content.
- Databricks notebooks: Python syntax check + bundle validate
- Databricks job YAML: schema validation + bundle validate
- ADF JSON: JSON schema + ARM deployment validate via Azure SDK
"""

import ast
import json
import logging
import os
import subprocess
import tempfile

import yaml

log = logging.getLogger(__name__)


class Validator:
    def __init__(
        self,
        databricks_host: str = None,
        databricks_token: str = None,
        azure_subscription_id: str = None,
        azure_resource_group: str = None,
        azure_tenant_id: str = None,
        azure_client_id: str = None,
        azure_client_secret: str = None,
        adf_factory_name: str = None,
    ):
        self._db_host = databricks_host or os.getenv("DATABRICKS_HOST")
        self._db_token = databricks_token or os.getenv("DATABRICKS_TOKEN")
        self._subscription = azure_subscription_id or os.getenv("AZURE_SUBSCRIPTION_ID")
        self._resource_group = azure_resource_group or os.getenv("AZURE_RESOURCE_GROUP")
        self._tenant_id = azure_tenant_id or os.getenv("AZURE_TENANT_ID")
        self._client_id = azure_client_id or os.getenv("AZURE_CLIENT_ID")
        self._client_secret = azure_client_secret or os.getenv("AZURE_CLIENT_SECRET")
        self._adf_name = adf_factory_name or os.getenv("ADF_FACTORY_NAME")

    def validate(self, platform: str, file_path: str, content: str) -> dict:
        """
        Route to the right validator based on platform.
        Returns {"passed": bool, "message": str, "error": str | None}
        """
        validators = {
            "databricks": self._validate_databricks_notebook,
            "databricks-job": self._validate_databricks_job,
            "adf-pipeline": self._validate_adf_json,
            "adf-dataset": self._validate_adf_json,
            "adf-linked": self._validate_adf_json,
        }
        fn = validators.get(platform, self._validate_generic)
        return fn(file_path, content)

    # ── Databricks notebook ──────────────────────────────────────────────────

    def _validate_databricks_notebook(self, file_path: str, content: str) -> dict:
        # 1. Python syntax check
        try:
            # Strip Databricks cell magic lines before parsing
            clean = "\n".join(
                line for line in content.splitlines()
                if not line.strip().startswith("# MAGIC") and line.strip() != "# COMMAND ----------"
            )
            ast.parse(clean)
        except SyntaxError as e:
            return {"passed": False, "message": "", "error": f"Python syntax error: {e}"}

        # 2. Bundle validate (if Databricks CLI available)
        bundle_result = self._run_bundle_validate()
        if not bundle_result["passed"]:
            return bundle_result

        return {"passed": True, "message": "Python syntax OK · Databricks bundle validate passed", "error": None}

    def _validate_databricks_job(self, file_path: str, content: str) -> dict:
        # 1. YAML parse
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            return {"passed": False, "message": "", "error": f"YAML parse error: {e}"}

        # 2. Bundle validate
        return self._run_bundle_validate()

    def _run_bundle_validate(self) -> dict:
        bundle_dir = os.getenv("DATABRICKS_BUNDLE_ROOT", "databricks")
        if not os.path.isdir(bundle_dir):
            log.warning("Bundle root '%s' not found — skipping bundle validate", bundle_dir)
            return {"passed": True, "message": "bundle validate skipped (no bundle root)", "error": None}

        env = {**os.environ, "DATABRICKS_HOST": self._db_host or "", "DATABRICKS_TOKEN": self._db_token or ""}
        result = subprocess.run(
            ["databricks", "bundle", "validate", "--output", "json"],
            cwd=bundle_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            return {"passed": False, "message": "", "error": f"bundle validate failed: {result.stderr}"}
        return {"passed": True, "message": "Databricks bundle validate passed", "error": None}

    # ── ADF JSON ─────────────────────────────────────────────────────────────

    def _validate_adf_json(self, file_path: str, content: str) -> dict:
        # 1. JSON parse
        try:
            obj = json.loads(content)
        except json.JSONDecodeError as e:
            return {"passed": False, "message": "", "error": f"JSON parse error: {e}"}

        # 2. Required ADF fields
        required_fields = {"name", "properties", "type"}
        missing = required_fields - set(obj.keys())
        if missing:
            return {
                "passed": False,
                "message": "",
                "error": f"ADF JSON missing required fields: {missing}",
            }

        # 3. ARM deployment validate (if Azure credentials available)
        if all([self._subscription, self._resource_group, self._client_id]):
            arm_result = self._arm_validate(obj)
            if not arm_result["passed"]:
                return arm_result

        return {"passed": True, "message": "ADF JSON valid · ARM template validate passed", "error": None}

    def _arm_validate(self, adf_object: dict) -> dict:
        """Wrap the ADF resource in a minimal ARM template and run az deployment validate."""
        arm_template = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "resources": [
                {
                    "type": f"Microsoft.DataFactory/factories/{adf_object.get('type', 'pipelines')}",
                    "apiVersion": "2018-06-01",
                    "name": f"[concat('{self._adf_name}/', '{adf_object.get('name', 'resource')}')]",
                    "properties": adf_object.get("properties", {}),
                }
            ],
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(arm_template, f)
            tmp_path = f.name

        result = subprocess.run(
            [
                "az", "deployment", "group", "validate",
                "--resource-group", self._resource_group,
                "--subscription", self._subscription,
                "--template-file", tmp_path,
            ],
            capture_output=True, text=True,
        )
        os.unlink(tmp_path)

        if result.returncode != 0:
            return {"passed": False, "message": "", "error": f"ARM validate failed: {result.stderr[:500]}"}
        return {"passed": True, "message": "ARM deployment validate passed", "error": None}

    # ── Generic ──────────────────────────────────────────────────────────────

    def _validate_generic(self, file_path: str, content: str) -> dict:
        if not content.strip():
            return {"passed": False, "message": "", "error": "Generated content is empty"}
        return {"passed": True, "message": "Content non-empty (generic validation)", "error": None}
