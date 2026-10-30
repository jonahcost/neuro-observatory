import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

MODULE = Path(__file__).resolve().parents[1] / "check_governance.py"
spec = importlib.util.spec_from_file_location("governance_check", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class GovernanceTests(unittest.TestCase):
    def test_impl_classification(self):
        self.assertTrue(mod.is_implementation("services/neuro-engine/pyproject.toml"))
        self.assertTrue(mod.is_implementation(".github/workflows/governance.yml"))
        self.assertFalse(mod.is_implementation("docs/user-guide.md"))

    def test_restricted_paths(self):
        for p in ("data/subject1.dcm", "sessions/raw.xdf", ".env", "services/neuro-engine/.venv/bin/python", "anatomy/scan.nii.gz"):
            if p == "sessions/raw.xdf":
                self.assertTrue(mod.is_sensitive_path(p))
            else:
                self.assertTrue(mod.is_sensitive_path(p))
        self.assertFalse(mod.is_sensitive_path(".env.example"))

    def test_code_without_adr_fails(self):
        with TemporaryDirectory() as temp:
            errors = mod.check_change_set(["apps/desktop/src/main.tsx"], Path(temp))
            self.assertEqual(len(errors), 2)

    def test_docs_only_is_exempt(self):
        with TemporaryDirectory() as temp:
            self.assertEqual(mod.check_change_set(["docs/readme.md"], Path(temp)), [])

    def test_paired_valid_adr_and_work_pass(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            adr = "docs/architecture/decisions/ADR-9999-example.md"
            work = "docs/work/completed/WORK-2026-10-29-example.md"
            (root / adr).parent.mkdir(parents=True)
            (root / work).parent.mkdir(parents=True)
            sections_a = "\n".join(f"## {s}\n\nA meaningful explanation of our chosen approach and tradeoffs.\n" for s in mod.ADR_SECTIONS)
            sections_w = "\n".join(f"## {s}\n\nActual, meaningful explanation of outcomes and test evidence.\n" for s in mod.WORK_SECTIONS)
            (root / adr).write_text(f"# ADR\n\n- Status: Accepted\n- Decision Owner: Project owner\n- Related Work: `{work}`\n\n{sections_a}")
            (root / work).write_text(f"# Work\n\n- Status: Completed\n- ADRs: `{adr}`\n\n{sections_w}")
            self.assertEqual(mod.check_change_set(["apps/desktop/src/main.tsx", adr, work], root), [])


if __name__ == "__main__":
    unittest.main()
