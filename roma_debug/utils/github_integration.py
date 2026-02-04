"""GitHub repo lifecycle utilities for ROMA Debug."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GitHubManager:
    """Manage cloning and PR creation for GitHub repos."""

    base_dir: Path

    @classmethod
    def from_env(cls) -> "GitHubManager":
        root = os.environ.get("ROMA_GH_REPO_ROOT", "").strip()
        if root:
            base = Path(root).expanduser().resolve()
        else:
            base = Path(tempfile.gettempdir()) / "roma_debug_repos"
        base.mkdir(parents=True, exist_ok=True)
        return cls(base_dir=base)

    def clone_repo(self, repo_url: str) -> str:
        repo_url = repo_url.strip()
        if not repo_url:
            raise ValueError("repo_url is required")

        dest_dir = self.base_dir / f"repo_{int(time.time())}"
        dest_dir.mkdir(parents=True, exist_ok=False)

        clone_url = self._with_token(repo_url)
        cmd = ["git", "clone", "--depth", "1", clone_url, str(dest_dir)]
        self._run(cmd)
        return str(dest_dir)

    def create_branch(self, repo_path: str, branch_name: str) -> None:
        self._ensure_repo_path(repo_path)
        self._run(["git", "checkout", "-B", branch_name], cwd=repo_path)

    def commit_and_push(self, repo_path: str, message: str) -> None:
        self._ensure_repo_path(repo_path)
        self._run(["git", "add", "."], cwd=repo_path)
        self._run(["git", "commit", "-m", message], cwd=repo_path)
        self._run(["git", "push", "-u", "origin", "HEAD"], cwd=repo_path)

    def create_pr(self, repo_path: str, title: str, body: str) -> Optional[str]:
        """Create a PR via gh CLI if available. Returns PR URL if created."""
        self._ensure_repo_path(repo_path)
        if not self._has_gh_cli():
            return None

        cmd = [
            "gh",
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
        ]
        try:
            out = self._run(cmd, cwd=repo_path)
        except RuntimeError:
            return None
        return out.strip() if out else None

    def cleanup_repo(self, repo_path: str) -> None:
        self._ensure_repo_path(repo_path)
        shutil.rmtree(repo_path, ignore_errors=True)

    def _ensure_repo_path(self, repo_path: str) -> None:
        repo = Path(repo_path).resolve()
        if not str(repo).startswith(str(self.base_dir.resolve()) + os.sep):
            raise ValueError("Invalid repo path")
        if not (repo / ".git").exists():
            raise ValueError("Not a git repository")

    def _with_token(self, repo_url: str) -> str:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not token:
            return repo_url
        if repo_url.startswith("https://"):
            return repo_url.replace("https://", f"https://{token}@")
        return repo_url

    def _has_gh_cli(self) -> bool:
        return shutil.which("gh") is not None

    def _run(self, cmd: list[str], cwd: Optional[str] = None) -> str:
        try:
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr.strip() or "Command failed") from exc
        return completed.stdout.strip()
