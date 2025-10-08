import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "TitanScraper.spec"


def test_titanscraper_spec_exists_and_nonempty():
    """Sentinel test: ensure PyInstaller spec file is present & has substance.

    Rationale: Our packaging scripts prefer `TitanScraper.spec` and fall back to
    more fragile dynamic invocation if it's missing. Losing or emptying this
    file silently degrades release quality (missing data files / optimizations).

    If this test fails:
      1. Restore the spec from git history (e.g. `git checkout <last-good> -- TitanScraper.spec`)
      2. Or regenerate a baseline with: `pyinstaller --name TitanScraper desktop/main.py` then
         adapt it (datas / binaries / opts) to match previous behavior.
    """
    assert SPEC_FILE.exists(), "TitanScraper.spec is missing (restore or regenerate it)."
    text = SPEC_FILE.read_text(encoding="utf-8", errors="ignore").strip()
    # Heuristic: require at least a few non-comment lines
    meaningful = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]  # noqa: E501
    assert len(meaningful) >= 5, "TitanScraper.spec looks unexpectedly empty; investigate corruption."  # noqa: E501


@pytest.mark.parametrize("filename", ["TitanScraperDashboard.spec"], ids=["dashboard-spec"])
def test_optional_other_spec_files_present(filename):
    path = ROOT / filename
    if not path.exists():
        pytest.skip(f"Optional spec '{filename}' not present (skip)")
    assert path.stat().st_size > 100, f"Spec '{filename}' seems too small; check integrity."  # noqa: E501
