"""Skill-local tests for the TDD guide script contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from coverage_analyzer import CoverageAnalyzer
from fixture_generator import FixtureGenerator
from format_detector import FormatDetector
from tdd_workflow import TDDWorkflow


SCRIPT_DIR = Path(__file__).resolve().parent


class CliContractTests(unittest.TestCase):
    """Verify documented CLI and critical library behavior."""

    def run_script(self, script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_DIR / script_name), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_advertised_scripts_have_help(self) -> None:
        for script_name in [
            "coverage_analyzer.py",
            "fixture_generator.py",
            "format_detector.py",
            "framework_adapter.py",
            "metrics_calculator.py",
            "output_formatter.py",
            "tdd_workflow.py",
            "test_generator.py",
        ]:
            with self.subTest(script=script_name):
                result = self.run_script(script_name, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_format_detector_cli_detects_python_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
            handle.write("import os\n\n\ndef test_example():\n    assert True\n")
            path = handle.name
        try:
            result = self.run_script("format_detector.py", "--file", path)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["language"], "python")
            self.assertEqual(payload["framework"], "pytest")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_coverage_invalid_json_reports_error(self) -> None:
        analyzer = CoverageAnalyzer()
        with self.assertRaises(ValueError):
            analyzer.detect_format("{not json")

    def test_format_detector_does_not_swallow_json_parse_as_success(self) -> None:
        detector = FormatDetector()
        self.assertEqual(detector.detect_coverage_format("{not json"), "unknown")

    def test_yaml_fixture_uses_pyyaml_semantics(self) -> None:
        content = FixtureGenerator().generate_fixture_file(
            "sample",
            {"name": "Ada Lovelace", "items": ["alpha", "beta"]},
            "yaml",
        )
        self.assertIn("name: Ada Lovelace", content)
        self.assertIn("- alpha", content)

    def test_refactor_quality_can_fail(self) -> None:
        workflow = TDDWorkflow()
        self.assertFalse(workflow._check_quality_improvement("x = 1\n", "x = 1\n"))


if __name__ == "__main__":
    unittest.main()
