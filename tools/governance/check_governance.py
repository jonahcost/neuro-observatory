#!/usr/bin/env python3
"""Structural, zero-dependency governance check for PR changes or all docs.

Does NOT certify owner approval, numerical validity or electrical safety.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ADR_ROOT = Path("docs/architecture/decisions")
WORK_ROOT = Path("docs/work/completed")
ADR_RE = re.compile(r"^docs/architecture/decisions/ADR-\d{4}-[a-z0-9-]+\.md$")
WORK_RE = re.compile(r"^docs/work/completed/WORK-\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")
ADR_SECTIONS = ["Context", "Decision", "Alternatives Considered", "Consequences", "Validation and Rollback"]
WORK_SECTIONS = ["Objective", "Scope", "Acceptance Criteria", "Implementation Summary", "Validation Evidence", "Risks and Follow-ups", "Human Review"]
PROTECTED_ROOT = {"AGENTS.md", "CLAUDE.md", ".cursorignore", "nx.json", "package.json", "yarn.lock", ".yarnrc.yml"}
PROTECTED_PREFIX = ("apps/", "services/", "packages/", "pipelines/", "hardware/", "tools/", ".cursor/", ".github/")
RESTRICTED_EXTENSIONS = (".dcm", ".nii", ".nii.gz", ".edf", ".bdf", ".xdf", ".fif")


def is_implementation(path: str) -> bool:
    return path in PROTECTED_ROOT or path.startswith(PROTECTED_PREFIX)


def is_sensitive_path(path: str) -> bool:
    pp = Path(path)
    name = pp.name.lower()
    if name == ".env" or (name.startswith(".env.") and name not in (".env.example", ".env.template")):
        return True
    return path.startswith(("data/", "datasets/", "recordings/", "models/", "artifacts/")) or "/.venv/" in f"/{path}/" or name.endswith(RESTRICTED_EXTENSIONS)


def check_document(path: Path, kind: str) -> list[str]:
    issues = []
    if not path.is_file():
        return [f"Missing: {path}"]
    text = path.read_text(encoding="utf-8")
    sections = ADR_SECTIONS if kind == "adr" else WORK_SECTIONS
    desired = "Accepted" if kind == "adr" else "Completed"
    if not re.search(rf"(?m)^- Status: {desired}\s*$", text):
        issues.append(f"{path}: Status must be {desired}")
    for sec in sections:
        # Ensure a meaningful body, not just a placeholder heading.
        pat = rf"(?ms)^## {re.escape(sec)}\s*\n(.*?)(?=^## |\Z)"
        m = re.search(pat, text)
        body = (m.group(1).strip() if m else "")
        if len(body) < 15 or re.search(r"\bTODO:\b|^TODO:", body, flags=re.IGNORECASE):
            issues.append(f"{path}: Missing/placeholder section ## {sec}")
    if kind == "adr":
        if not re.search(r"(?m)^- Decision Owner: .+", text):
            issues.append(f"{path}: Missing Decision Owner")
        if not re.search(r"(?m)^- Related Work: .+", text):
            issues.append(f"{path}: Missing Related Work")
    else:
        if not re.search(r"(?m)^- ADRs: .+", text):
            issues.append(f"{path}: Missing ADRs reference")
    return issues


def changed_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base, head],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def check_change_set(paths: list[str], root: Path) -> list[str]:
    issues = []
    exposed = [p for p in paths if is_sensitive_path(p)]
    if exposed:
        issues.append("Restricted data/files in change set: " + ", ".join(exposed))
    if not any(is_implementation(p) for p in paths):
        return issues  # prose-only changes do not need a new ADR
    adrs = [p for p in paths if ADR_RE.fullmatch(p)]
    works = [p for p in paths if WORK_RE.fullmatch(p)]
    if not adrs:
        issues.append("Implementation/config change requires an added or updated accepted ADR in this PR")
    if not works:
        issues.append("Implementation/config change requires an added or updated completed WORK record in this PR")
    for a in adrs:
        issues.extend(check_document(root / a, "adr"))
    for record in works:
        issues.extend(check_document(root / record, "work"))
        content = (root / record).read_text(encoding="utf-8") if (root / record).exists() else ""
        if adrs and not any(Path(a).name in content for a in adrs):
            issues.append(f"{record}: Must reference at least one changed ADR")
    for a in adrs:
        content = (root / a).read_text(encoding="utf-8") if (root / a).exists() else ""
        if works and not any(Path(w).name in content for w in works):
            issues.append(f"{a}: Must reference a changed completed WORK record")
    return issues


def validate_all(root: Path) -> list[str]:
    issues = []
    for f in sorted((root / ADR_ROOT).glob("ADR-????-*.md")):
        text = f.read_text(encoding="utf-8")
        if re.search(r"(?m)^- Status: Accepted\s*$", text):
            issues.extend(check_document(f, "adr"))
        elif not re.search(r"(?m)^- Status: (Proposed|Rejected|Superseded)\s*$", text):
            issues.append(f"{f}: unrecognized ADR status")
    for f in sorted((root / WORK_ROOT).glob("WORK-*.md")):
        issues.extend(check_document(f, "work"))
    # This is NOT a content/secret scanner. The check relies on Git tracked paths.
    try:
        result = subprocess.run(["git", "ls-files"], cwd=root, text=True, capture_output=True, check=True)
        tracked = result.stdout.splitlines()
        unsafe = [path for path in tracked if is_sensitive_path(path)]
        if unsafe:
            issues.append("Restricted tracked paths: " + ", ".join(unsafe))
    except (OSError, subprocess.CalledProcessError):
        pass
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="Git base SHA for PR validation")
    parser.add_argument("--head", help="Git head SHA for PR validation")
    parser.add_argument("--all", action="store_true", help="Validate all accepted ADRs and completed work records")
    args = parser.parse_args()
    if args.all:
        issues = validate_all(ROOT)
    elif args.base and args.head:
        try:
            issues = check_change_set(changed_paths(args.base, args.head), ROOT)
        except subprocess.CalledProcessError as exc:
            print(f"git diff failed: {exc.stderr}", file=sys.stderr)
            return 2
    else:
        parser.error("pass --all or both --base and --head")
    if issues:
        print("Governance failed:")
        for issue in issues:
            print(" -", issue)
        return 1
    print("Governance check passed. Human review and scientific/safety validation still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
