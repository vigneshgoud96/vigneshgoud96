"""
GitHub API operations:
  - Get file content + SHA from repo
  - Create feature branch
  - Commit modified file
  - Push (implicit via GitHub API)
  - Raise pull request with reviewers, labels, body
"""

import base64
import logging
import os
from github import Github, GithubException

log = logging.getLogger(__name__)


class GitOps:
    def __init__(self, token: str, repo_name: str, base_branch: str = "main"):
        self._gh = Github(token)
        self._repo = self._gh.get_repo(repo_name)
        self._base_branch = base_branch
        log.info("Connected to repo: %s (base: %s)", repo_name, base_branch)

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_file(self, file_path: str) -> tuple[str, str]:
        """
        Returns (decoded_content, sha) for the file at file_path on base branch.
        If file does not exist, returns ("", "") — caller handles create vs modify.
        """
        try:
            contents = self._repo.get_contents(file_path, ref=self._base_branch)
            decoded = base64.b64decode(contents.content).decode("utf-8")
            log.info("Fetched %s (%d bytes, sha=%s)", file_path, len(decoded), contents.sha[:8])
            return decoded, contents.sha
        except GithubException as e:
            if e.status == 404:
                log.info("File %s not found — will create", file_path)
                return "", ""
            raise

    def list_files(self, directory: str = "") -> list[str]:
        """Return list of all file paths under directory."""
        paths = []
        try:
            contents = self._repo.get_contents(directory, ref=self._base_branch)
            while contents:
                item = contents.pop(0)
                if item.type == "dir":
                    contents.extend(self._repo.get_contents(item.path, ref=self._base_branch))
                else:
                    paths.append(item.path)
        except GithubException:
            pass
        return paths

    # ── Write ────────────────────────────────────────────────────────────────

    def commit_and_pr(
        self,
        branch_name: str,
        file_path: str,
        new_content: str,
        current_sha: str,
        commit_message: str,
        pr_title: str,
        pr_body: str,
        reviewers: list[str] = None,
        labels: list[str] = None,
    ) -> dict:
        """
        1. Create branch from base
        2. Create or update file
        3. Create PR
        Returns {"branch": str, "commit_sha": str, "pr_url": str, "pr_number": int}
        """
        # 1. Create branch
        base_ref = self._repo.get_git_ref(f"heads/{self._base_branch}")
        base_sha = base_ref.object.sha
        self._repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
        log.info("Created branch: %s (from %s)", branch_name, base_sha[:8])

        # 2. Commit file
        encoded = new_content.encode("utf-8")
        if current_sha:
            result = self._repo.update_file(
                path=file_path,
                message=commit_message,
                content=encoded,
                sha=current_sha,
                branch=branch_name,
            )
        else:
            result = self._repo.create_file(
                path=file_path,
                message=commit_message,
                content=encoded,
                branch=branch_name,
            )
        commit_sha = result["commit"].sha
        log.info("Committed %s → %s", file_path, commit_sha[:10])

        # 3. Ensure labels exist
        clean_labels = []
        for label_name in (labels or []):
            label_name = label_name.strip()
            if not label_name:
                continue
            try:
                self._repo.get_label(label_name)
            except GithubException:
                self._repo.create_label(label_name, color="0075ca")
            clean_labels.append(label_name)

        # 4. Create PR
        pr = self._repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base=self._base_branch,
            draft=False,
        )
        if clean_labels:
            pr.add_to_labels(*clean_labels)

        # 5. Request reviewers (ignore errors for users not in repo)
        clean_reviewers = [r.strip() for r in (reviewers or []) if r.strip()]
        if clean_reviewers:
            try:
                pr.create_review_request(reviewers=clean_reviewers)
            except GithubException as e:
                log.warning("Could not add reviewers: %s", e)

        log.info("PR raised: %s (#%d)", pr.html_url, pr.number)
        return {
            "branch": branch_name,
            "commit_sha": commit_sha,
            "pr_url": pr.html_url,
            "pr_number": pr.number,
        }

    def delete_branch(self, branch_name: str) -> None:
        """Clean up a branch (e.g. after failed validation)."""
        try:
            ref = self._repo.get_git_ref(f"heads/{branch_name}")
            ref.delete()
            log.info("Deleted branch: %s", branch_name)
        except GithubException as e:
            log.warning("Could not delete branch %s: %s", branch_name, e)
