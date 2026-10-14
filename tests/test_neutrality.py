"""Customer neutrality: no emails, workspace hosts, or denylisted names in the repository.

Optional: set LSI_NEUTRALITY_DENYLIST to comma-separated terms (for example customer names) to check too.
"""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
WORKSPACE_HOST = re.compile(r"adb-\d{6,}\.\d+\.azuredatabricks\.net|[\w-]+\.cloud\.databricks\.com")
ALLOWED_EMAILS = {"noreply@anthropic.com"}


def tracked_text_files():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for name in files:
        path = ROOT / name
        if path.suffix in {".py", ".md", ".yml", ".yaml", ".toml", ".txt"} and path.name != Path(__file__).name:
            yield name, path.read_text(encoding="utf-8", errors="ignore")


def test_no_emails_hosts_or_denylisted_terms():
    denylist = [t.strip().lower() for t in os.environ.get("LSI_NEUTRALITY_DENYLIST", "").split(",") if t.strip()]
    findings = []
    for name, text in tracked_text_files():
        findings += [f"{name}: email {m}" for m in EMAIL.findall(text) if m not in ALLOWED_EMAILS]
        findings += [f"{name}: workspace host {m}" for m in WORKSPACE_HOST.findall(text)]
        findings += [f"{name}: denylisted {t}" for t in denylist if t in text.lower()]
    assert not findings, "\n".join(findings)
