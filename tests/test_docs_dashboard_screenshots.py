"""Tests for Fase 11B Gate C - the real dashboard screenshots captured
via a live Streamlit server + Selenium (headless Edge), and their
presence/linking from README.md and PORTFOLIO.md.

These are pure filesystem/text checks - no Streamlit server, no
Selenium, no CredLens import - fast enough for the default (non-slow)
suite.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = REPO_ROOT / "docs" / "assets" / "dashboard"

# The 10 real pages under dashboard/pages/ (Fase 13: 2 were added after
# Fase 11B section 13's original 8-page list - vintages_roll_rates and
# cure_collections_recovery - and the screenshot set had drifted out of
# sync with it ever since; confirmed via `ls dashboard/pages/` and fixed
# by capturing the 2 missing captures from a real container run).
REQUIRED_SCREENSHOTS = (
    "executive_overview.png",
    "credit_funnel.png",
    "portfolio_delinquency.png",
    "vintages_roll_rates.png",
    "cure_collections_recovery.png",
    "scenario_lab.png",
    "model_lab.png",
    "model_monitoring_lab.png",
    "public_benchmarks.png",
    "data_quality.png",
)

# Generous ceilings - real regressions (a broken capture, a runaway
# resolution) would blow way past these, while leaving headroom for
# legitimate future recaptures at a different resolution.
_MIN_DIMENSION_PX = 800
_MAX_SINGLE_FILE_BYTES = 3 * 1024 * 1024
_MAX_TOTAL_BYTES = 15 * 1024 * 1024


class TestScreenshotsExist:
    def test_every_required_screenshot_is_present(self) -> None:
        missing = [name for name in REQUIRED_SCREENSHOTS if not (SCREENSHOT_DIR / name).is_file()]
        assert missing == [], f"missing screenshot(s) under {SCREENSHOT_DIR}: {missing}"

    def test_no_mockup_placeholder_naming(self) -> None:
        """A cheap guard against a generated/mockup image being dropped
        in instead of a real capture - Fase 11B explicitly forbids
        mockups. Real filenames only; this doesn't prove the CONTENT is
        real (that needs a human/visual check), only that nothing
        obviously labels itself as a placeholder."""
        for name in REQUIRED_SCREENSHOTS:
            path = SCREENSHOT_DIR / name
            if not path.is_file():
                continue
            assert "mockup" not in name.lower()
            assert "placeholder" not in name.lower()


class TestScreenshotDimensionsAndSize:
    def test_every_screenshot_has_a_reasonable_resolution(self) -> None:
        for name in REQUIRED_SCREENSHOTS:
            path = SCREENSHOT_DIR / name
            if not path.is_file():
                continue
            with Image.open(path) as img:
                width, height = img.size
            assert width >= _MIN_DIMENSION_PX, f"{name}: width={width} too small"
            assert height >= _MIN_DIMENSION_PX, f"{name}: height={height} too small"

    def test_every_screenshot_is_a_valid_png(self) -> None:
        for name in REQUIRED_SCREENSHOTS:
            path = SCREENSHOT_DIR / name
            if not path.is_file():
                continue
            with Image.open(path) as img:
                img.verify()
                assert img.format == "PNG", f"{name}: format={img.format!r}, expected PNG"

    def test_all_screenshots_share_the_same_resolution(self) -> None:
        """Not a hard product requirement, but consistent resolution
        across a single capture session is a strong signal of a real,
        uniform capture pipeline rather than ad hoc/mismatched images."""
        dimensions = set()
        for name in REQUIRED_SCREENSHOTS:
            path = SCREENSHOT_DIR / name
            if not path.is_file():
                continue
            with Image.open(path) as img:
                dimensions.add(img.size)
        assert len(dimensions) <= 1, f"inconsistent screenshot resolutions: {dimensions}"

    def test_no_single_file_exceeds_the_size_ceiling(self) -> None:
        for name in REQUIRED_SCREENSHOTS:
            path = SCREENSHOT_DIR / name
            if not path.is_file():
                continue
            size = path.stat().st_size
            assert size <= _MAX_SINGLE_FILE_BYTES, f"{name}: {size} bytes exceeds ceiling"
            assert size > 0, f"{name}: empty file"

    def test_total_screenshot_budget_is_reasonable(self) -> None:
        total = sum(
            (SCREENSHOT_DIR / name).stat().st_size
            for name in REQUIRED_SCREENSHOTS
            if (SCREENSHOT_DIR / name).is_file()
        )
        assert total <= _MAX_TOTAL_BYTES, f"total screenshot size {total} bytes exceeds budget"


class TestReadmeLinksToScreenshots:
    def _referenced_dashboard_image_paths(self, text: str) -> list[str]:
        # Fase 11B section 14 explicitly accepts either an embedded
        # mosaic OR plain links to the remaining screenshots - so a
        # bare markdown link (no leading `!`) counts as a reference
        # too, not just an embedded image.
        markdown_refs = re.findall(r"\]\((docs/assets/dashboard/[^)\s]+)\)", text)
        html_refs = re.findall(r'src="(docs/assets/dashboard/[^"]+)"', text)
        href_refs = re.findall(r'href="(docs/assets/dashboard/[^"]+)"', text)
        return markdown_refs + html_refs + href_refs

    def test_readme_references_at_least_one_real_screenshot_near_the_top(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        first_heading_index = text.index("\n## ")
        top_section = text[:first_heading_index]
        assert "docs/assets/dashboard/executive_overview.png" in top_section

    def test_every_readme_screenshot_reference_resolves_to_a_real_file(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        referenced = self._referenced_dashboard_image_paths(text)
        assert referenced, "expected at least one docs/assets/dashboard/ reference in README.md"
        for rel_path in referenced:
            assert (REPO_ROOT / rel_path).is_file(), (
                f"README.md references {rel_path!r}, which does not exist on disk "
                "(paths are case-sensitive on GitHub's Linux-backed rendering)"
            )

    def test_readme_image_references_have_non_empty_alt_text(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for alt_text, rel_path in re.findall(
            r"!\[([^\]]*)\]\((docs/assets/dashboard/[^)\s]+)\)", text
        ):
            assert alt_text.strip(), f"empty alt text for image {rel_path!r}"

    def test_readme_references_every_required_screenshot_at_least_once(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        referenced = set(self._referenced_dashboard_image_paths(text))
        referenced_names = {Path(p).name for p in referenced}
        missing = [name for name in REQUIRED_SCREENSHOTS if name not in referenced_names]
        assert missing == [], f"README.md never references: {missing}"

    def test_portfolio_references_the_primary_screenshot(self) -> None:
        text = (REPO_ROOT / "PORTFOLIO.md").read_text(encoding="utf-8")
        assert "docs/assets/dashboard/executive_overview.png" in text
        referenced = self._referenced_dashboard_image_paths(text)
        for rel_path in referenced:
            assert (REPO_ROOT / rel_path).is_file()
