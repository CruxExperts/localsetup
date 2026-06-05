"""
Metrics calculation module.

Calculate comprehensive test and code quality metrics including complexity,
test quality scoring, and test execution analysis.
"""

from typing import Dict, List, Any, Optional
import argparse
import re

from cli_support import SkillCliError, emit_json, fail, read_json, read_text
from metrics_complexity import (
    cognitive_complexity,
    complexity_assessment,
    cyclomatic_complexity,
    testability_score,
)


class MetricsCalculator:
    """Calculate comprehensive test and code quality metrics."""

    def __init__(self):
        """Initialize metrics calculator."""
        self.metrics = {}

    def calculate_all_metrics(
        self,
        source_code: str,
        test_code: str,
        coverage_data: Optional[Dict[str, Any]] = None,
        execution_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate all available metrics.

        Args:
            source_code: Source code to analyze
            test_code: Test code to analyze
            coverage_data: Coverage report data
            execution_data: Test execution results

        Returns:
            Complete metrics dictionary
        """
        metrics = {
            'complexity': self.calculate_complexity(source_code),
            'test_quality': self.calculate_test_quality(test_code),
            'coverage': coverage_data or {},
            'execution': execution_data or {}
        }

        self.metrics = metrics
        return metrics

    def calculate_complexity(self, code: str) -> Dict[str, Any]:
        """
        Calculate code complexity metrics.

        Args:
            code: Source code to analyze

        Returns:
            Complexity metrics (cyclomatic, cognitive, testability score)
        """
        cyclomatic = self._cyclomatic_complexity(code)
        cognitive = self._cognitive_complexity(code)
        testability = self._testability_score(code, cyclomatic)

        return {
            'cyclomatic_complexity': cyclomatic,
            'cognitive_complexity': cognitive,
            'testability_score': testability,
            'assessment': self._complexity_assessment(cyclomatic, cognitive)
        }

    def _cyclomatic_complexity(self, code: str) -> int:
        return cyclomatic_complexity(code)

    def _cognitive_complexity(self, code: str) -> int:
        return cognitive_complexity(code)

    def _testability_score(self, code: str, cyclomatic: int) -> float:
        return testability_score(code, cyclomatic)

    def _complexity_assessment(self, cyclomatic: int, cognitive: int) -> str:
        return complexity_assessment(cyclomatic, cognitive)

    def calculate_test_quality(self, test_code: str) -> Dict[str, Any]:
        """
        Calculate test quality metrics.

        Args:
            test_code: Test code to analyze

        Returns:
            Test quality metrics
        """
        assertions = self._count_assertions(test_code)
        test_functions = self._count_test_functions(test_code)
        isolation_score = self._isolation_score(test_code)
        naming_quality = self._naming_quality(test_code)
        test_smells = self._detect_test_smells(test_code)

        avg_assertions = assertions / test_functions if test_functions > 0 else 0

        return {
            'total_tests': test_functions,
            'total_assertions': assertions,
            'avg_assertions_per_test': round(avg_assertions, 2),
            'isolation_score': isolation_score,
            'naming_quality': naming_quality,
            'test_smells': test_smells,
            'quality_score': self._calculate_quality_score(
                avg_assertions, isolation_score, naming_quality, test_smells
            )
        }

    def _count_assertions(self, test_code: str) -> int:
        """Count assertion statements."""
        # Common assertion patterns
        patterns = [
            r'\bassert[A-Z]\w*\(',  # JUnit: assertTrue, assertEquals
            r'\bexpect\(',  # Jest/Vitest: expect()
            r'\bassert\s+',  # Python: assert
            r'\.should\.',  # Chai: should
            r'\.to\.',  # Chai: expect().to
        ]

        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, test_code))

        return count

    def _count_test_functions(self, test_code: str) -> int:
        """Count test functions."""
        patterns = [
            r'\btest_\w+',  # Python: test_*
            r'\bit\(',  # Jest/Mocha: it()
            r'\btest\(',  # Jest: test()
            r'@Test',  # JUnit: @Test
            r'\bdef test_',  # Python def test_
        ]

        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, test_code))

        return max(1, count)  # At least 1 to avoid division by zero

    def _isolation_score(self, test_code: str) -> float:
        """
        Calculate test isolation score (0-100).

        Higher score = better isolation (fewer shared dependencies)
        """
        score = 100.0

        # Penalize global state
        globals_used = len(re.findall(r'\bglobal\s+\w+', test_code))
        score -= globals_used * 10

        # Penalize shared setup without proper cleanup
        setup_count = len(re.findall(r'beforeAll|beforeEach|setUp', test_code))
        cleanup_count = len(re.findall(r'afterAll|afterEach|tearDown', test_code))
        if setup_count > cleanup_count:
            score -= (setup_count - cleanup_count) * 5

        # Reward mocking
        mocks = len(re.findall(r'mock|stub|spy', test_code, re.IGNORECASE))
        score += min(mocks * 2, 10)

        return max(0.0, min(100.0, score))

    def _naming_quality(self, test_code: str) -> float:
        """
        Calculate test naming quality score (0-100).

        Better names are descriptive and follow conventions.
        """
        test_names = re.findall(r'(?:it|test|def test_)\s*\(?\s*["\']?([^"\')\n]+)', test_code)

        if not test_names:
            return 50.0

        score = 0
        for name in test_names:
            name_score = 0

            # Check length (too short or too long is bad)
            if 20 <= len(name) <= 80:
                name_score += 30
            elif 10 <= len(name) < 20 or 80 < len(name) <= 100:
                name_score += 15

            # Check for descriptive words
            descriptive_words = ['should', 'when', 'given', 'returns', 'throws', 'handles']
            if any(word in name.lower() for word in descriptive_words):
                name_score += 30

            # Check for underscores or camelCase (not just letters)
            if '_' in name or re.search(r'[a-z][A-Z]', name):
                name_score += 20

            # Avoid generic names
            generic = ['test1', 'test2', 'testit', 'mytest']
            if name.lower() not in generic:
                name_score += 20

            score += name_score

        return min(100.0, score / len(test_names))

    def _detect_test_smells(self, test_code: str) -> List[Dict[str, str]]:
        """Detect common test smells."""
        smells = []

        # Test smell 1: No assertions
        if 'assert' not in test_code.lower() and 'expect' not in test_code.lower():
            smells.append({
                'smell': 'missing_assertions',
                'description': 'Tests without assertions',
                'severity': 'high'
            })

        # Test smell 2: Too many assertions
        test_count = self._count_test_functions(test_code)
        assertion_count = self._count_assertions(test_code)
        avg_assertions = assertion_count / test_count if test_count > 0 else 0
        if avg_assertions > 5:
            smells.append({
                'smell': 'assertion_roulette',
                'description': f'Too many assertions per test (avg: {avg_assertions:.1f})',
                'severity': 'medium'
            })

        # Test smell 3: Sleeps in tests
        if 'sleep' in test_code.lower() or 'wait' in test_code.lower():
            smells.append({
                'smell': 'sleepy_test',
                'description': 'Tests using sleep/wait (potential flakiness)',
                'severity': 'high'
            })

        # Test smell 4: Conditional logic in tests
        if re.search(r'\bif\s*\(', test_code):
            smells.append({
                'smell': 'conditional_test_logic',
                'description': 'Tests contain conditional logic',
                'severity': 'medium'
            })

        return smells

    def _calculate_quality_score(
        self,
        avg_assertions: float,
        isolation: float,
        naming: float,
        smells: List[Dict[str, str]]
    ) -> float:
        """Calculate overall test quality score."""
        score = 0.0

        # Assertions (30 points)
        if 1 <= avg_assertions <= 3:
            score += 30
        elif 0 < avg_assertions < 1 or 3 < avg_assertions <= 5:
            score += 20
        else:
            score += 10

        # Isolation (30 points)
        score += isolation * 0.3

        # Naming (20 points)
        score += naming * 0.2

        # Smells (20 points - deduct based on severity)
        smell_penalty = 0
        for smell in smells:
            if smell['severity'] == 'high':
                smell_penalty += 10
            elif smell['severity'] == 'medium':
                smell_penalty += 5
            else:
                smell_penalty += 2

        score = max(0, score - smell_penalty)

        return round(min(100.0, score), 2)

    def analyze_execution_metrics(
        self,
        execution_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze test execution metrics.

        Args:
            execution_data: Test execution results with timing

        Returns:
            Execution analysis
        """
        tests = execution_data.get('tests', [])

        if not tests:
            return {}

        # Calculate timing statistics
        timings = [test.get('duration', 0) for test in tests]
        total_time = sum(timings)
        avg_time = total_time / len(tests) if tests else 0

        # Identify slow tests (>100ms for unit tests)
        slow_tests = [
            test for test in tests
            if test.get('duration', 0) > 100
        ]

        # Identify flaky tests (if failure history available)
        flaky_tests = [
            test for test in tests
            if test.get('failure_rate', 0) > 0.1  # Failed >10% of time
        ]

        return {
            'total_tests': len(tests),
            'total_time_ms': round(total_time, 2),
            'avg_time_ms': round(avg_time, 2),
            'slow_tests': len(slow_tests),
            'slow_test_details': slow_tests[:5],  # Top 5
            'flaky_tests': len(flaky_tests),
            'flaky_test_details': flaky_tests,
            'pass_rate': self._calculate_pass_rate(tests)
        }

    def _calculate_pass_rate(self, tests: List[Dict[str, Any]]) -> float:
        """Calculate test pass rate."""
        if not tests:
            return 0.0

        passed = sum(1 for test in tests if test.get('status') == 'passed')
        return round((passed / len(tests)) * 100, 2)

    def generate_metrics_summary(self) -> str:
        """Generate human-readable metrics summary."""
        if not self.metrics:
            return "No metrics calculated yet."

        lines = ["# Test Metrics Summary\n"]

        # Complexity
        if 'complexity' in self.metrics:
            comp = self.metrics['complexity']
            lines.append(f"## Code Complexity")
            lines.append(f"- Cyclomatic Complexity: {comp['cyclomatic_complexity']}")
            lines.append(f"- Cognitive Complexity: {comp['cognitive_complexity']}")
            lines.append(f"- Testability Score: {comp['testability_score']:.1f}/100")
            lines.append(f"- Assessment: {comp['assessment']}\n")

        # Test Quality
        if 'test_quality' in self.metrics:
            qual = self.metrics['test_quality']
            lines.append(f"## Test Quality")
            lines.append(f"- Total Tests: {qual['total_tests']}")
            lines.append(f"- Assertions per Test: {qual['avg_assertions_per_test']}")
            lines.append(f"- Isolation Score: {qual['isolation_score']:.1f}/100")
            lines.append(f"- Naming Quality: {qual['naming_quality']:.1f}/100")
            lines.append(f"- Quality Score: {qual['quality_score']:.1f}/100\n")

            if qual['test_smells']:
                lines.append(f"### Test Smells Detected:")
                for smell in qual['test_smells']:
                    lines.append(f"- {smell['description']} (severity: {smell['severity']})")
                lines.append("")

        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Calculate source complexity, test quality, and execution metrics."
    )
    parser.add_argument("--source", help="Path to source code.")
    parser.add_argument("--source-code", help="Inline source code.")
    parser.add_argument("--tests", help="Path to test code.")
    parser.add_argument("--test-code", help="Inline test code.")
    parser.add_argument("--coverage-json", help="Inline parsed coverage JSON.")
    parser.add_argument("--coverage-file", help="Path to parsed coverage JSON.")
    parser.add_argument("--execution-json", help="Inline execution result JSON.")
    parser.add_argument("--execution-file", help="Path to execution result JSON.")
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    calculator = MetricsCalculator()

    try:
        source_code = read_text(path=args.source, inline=args.source_code)
        test_code = read_text(path=args.tests, inline=args.test_code)
        coverage_data = read_json(args.coverage_file, args.coverage_json) if (
            args.coverage_file or args.coverage_json
        ) else None
        execution_data = read_json(args.execution_file, args.execution_json) if (
            args.execution_file or args.execution_json
        ) else None

        metrics = calculator.calculate_all_metrics(
            source_code, test_code, coverage_data, execution_data
        )
        if args.format == "markdown":
            print(calculator.generate_metrics_summary())
        else:
            emit_json(metrics)
        return 0
    except (SkillCliError, ValueError, KeyError, TypeError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
