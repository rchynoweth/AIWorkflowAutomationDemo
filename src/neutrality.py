"""Customer-neutrality scanner. Run: python -m src.neutrality"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from src.config import repo_root


# ====================================================================================================
# Customer-neutrality scanner (docs/CUSTOMER_NEUTRALITY_REVIEW.md, ADR-013)
# ====================================================================================================

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".databricks", "node_modules", ".idea",
             ".vscode", ".claude", "build", "dist"}
SKIP_FILES = {"LICENSE"}
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".csv", ".sql", ".json", ".cfg", ".ini", ".example",
                 ".gitignore", ".env", ".jsonl", ".html", ".sh", ".ps1"}
FORBIDDEN_SUFFIXES = {".pptx", ".ppt", ".docx", ".doc", ".pdf", ".xlsx", ".xls", ".msg", ".eml", ".key"}

ALLOWED_EMAILS = {"noreply@anthropic.com"}
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org"}
ALLOWED_HOST_PATTERNS = [
    r"localhost", r"127\.0\.0\.1", r"0\.0\.0\.0", r"example\.(com|org)", r"claude\.com", r"anthropic\.com",
    r"docs\.databricks\.com", r"learn\.microsoft\.com", r"github\.com/[\w.-]+/AIWorkflowAutomationDemo",
    r"accounts\.azuredatabricks\.net",
    # public documentation links in the standard Python .gitignore template
    r"python-poetry\.org", r"pdm-project\.org", r"github\.com/github/gitignore", r"abstra\.io",
]
# Files allowed to contain the risk-pattern vocabulary itself.
PATTERN_DEFINITION_FILES = {"src/neutrality.py", "tests/unit/test_evaluation_neutrality_ingestion.py"}

PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "url": re.compile(r"https?://[^\s)\"'<>\]]+"),
    "workspace_host": re.compile(r"adb-\d{6,}\.\d+\.azuredatabricks\.net|[\w-]+\.cloud\.databricks\.com"),
    "phone": re.compile(r"(?<![\w-])\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?![\w-])"),
    "ssn_like": re.compile(r"(?<![\w-])\d{3}-\d{2}-\d{4}(?![\w-])"),
    "street_address": re.compile(r"\b\d{2,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|"
                                 r"Lane|Ln|Drive|Dr|Court|Ct)\b"),
    "production_claim": re.compile(r"\b(?:our production (?:schema|policy|system)|actual (?:servicing )?policy of|"
                                   r"production schema of|real borrower data|copied from (?:the )?client)\b", re.I),
}


@dataclass
class Finding:
    path: str
    line: int
    category: str
    text: str


def _denylist() -> list[str]:
    raw = os.environ.get("LSI_NEUTRALITY_DENYLIST", "").strip()
    if not raw:
        return []
    path = Path(raw)
    if path.exists():
        terms = path.read_text(encoding="utf-8").splitlines()
    else:
        terms = raw.split(",")
    return [t.strip().lower() for t in terms if t.strip()]


def _host_allowed(url: str) -> bool:
    return any(re.search(p, url, re.I) for p in ALLOWED_HOST_PATTERNS)


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def scan_text(rel: str, text: str, denylist: list[str]) -> list[Finding]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for category, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                value = match.group(0)
                if category == "email":
                    domain = value.split("@", 1)[1].lower()
                    if value.lower() in ALLOWED_EMAILS or domain in ALLOWED_EMAIL_DOMAINS:
                        continue
                if category == "url" and _host_allowed(value):
                    continue
                if rel in PATTERN_DEFINITION_FILES:
                    continue  # scanner definitions and its own detection tests
                if category == "url" and re.search(r"\$\{|\{[a-z_]+\}|<[a-z-]+>", value):
                    continue  # placeholders
                findings.append(Finding(rel, lineno, category, value[:120]))
        lowered = line.lower()
        for term in denylist:
            if term in lowered:
                findings.append(Finding(rel, lineno, "denylist", term))
    return findings


def scan(root: Path | None = None) -> tuple[list[Finding], int]:
    root = root or repo_root()
    denylist = _denylist()
    findings: list[Finding] = []
    scanned = 0
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        if path.name in SKIP_FILES:
            continue
        lowered = rel.lower()
        for term in denylist:
            if term in lowered:
                findings.append(Finding(rel, 0, "denylist_filename", term))
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(Finding(rel, 0, "forbidden_document_type", path.suffix))
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".gitignore", ".env.example"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        findings.extend(scan_text(rel, text, denylist))
    return findings, scanned


def check_generated_names(root: Path | None = None) -> list[Finding]:
    """Generated people/organization names must follow the synthetic pattern."""
    import pandas as pd

    root = root or repo_root()
    gen = root / "data" / "generated"
    findings = []
    checks = [("loans.csv", "borrower_display_name", r"^Synthetic Borrower \d{4}$"),
              ("servicing_specialists.csv", "display_name", r"^Synthetic Specialist \d{2}$"),
              ("attorneys_vendors.csv", "display_name", r"^Synthetic (Legal|Servicing) Vendor \d{2}$"),
              ("loans.csv", "property_address", r"^Synthetic Address \d{4}$")]
    for filename, column, pattern in checks:
        path = gen / filename
        if not path.exists():
            continue
        values = pd.read_csv(path, dtype=str, keep_default_na=False)[column]
        bad = values[~values.str.match(pattern)]
        for v in bad.head(5):
            findings.append(Finding(f"data/generated/{filename}", 0, "non_synthetic_name", v))
    return findings


def main() -> int:
    findings, scanned = scan()
    findings += check_generated_names()
    print(f"Customer-neutrality scan: {scanned} text files scanned, {len(findings)} finding(s).")
    for f in findings[:200]:
        print(f"  {f.path}:{f.line} [{f.category}] {f.text}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
