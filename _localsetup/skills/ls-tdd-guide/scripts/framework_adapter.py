"""
Framework adapter module.

Provides multi-framework support with adapters for Jest, Pytest, JUnit, Vitest, and more.
Handles framework-specific patterns, imports, and test structure.
"""

from typing import Optional
import argparse
from enum import Enum

from cli_support import SkillCliError, emit_json, fail, read_text


class Framework(Enum):
    """Supported testing frameworks."""
    JEST = "jest"
    VITEST = "vitest"
    PYTEST = "pytest"
    UNITTEST = "unittest"
    JUNIT = "junit"
    TESTNG = "testng"
    MOCHA = "mocha"
    JASMINE = "jasmine"


class Language(Enum):
    """Supported programming languages."""
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    PYTHON = "python"
    JAVA = "java"


class FrameworkAdapter:
    """Adapter for multiple testing frameworks."""

    def __init__(self, framework: Framework, language: Language):
        """
        Initialize framework adapter.

        Args:
            framework: Testing framework
            language: Programming language
        """
        self.framework = framework
        self.language = language

    def generate_imports(self) -> str:
        """Generate framework-specific imports."""
        if self.framework == Framework.JEST:
            return self._jest_imports()
        elif self.framework == Framework.VITEST:
            return self._vitest_imports()
        elif self.framework == Framework.PYTEST:
            return self._pytest_imports()
        elif self.framework == Framework.UNITTEST:
            return self._unittest_imports()
        elif self.framework == Framework.JUNIT:
            return self._junit_imports()
        elif self.framework == Framework.TESTNG:
            return self._testng_imports()
        elif self.framework == Framework.MOCHA:
            return self._mocha_imports()
        else:
            return ""

    def _jest_imports(self) -> str:
        """Generate Jest imports."""
        return """import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';"""

    def _vitest_imports(self) -> str:
        """Generate Vitest imports."""
        return """import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';"""

    def _pytest_imports(self) -> str:
        """Generate Pytest imports."""
        return """import pytest"""

    def _unittest_imports(self) -> str:
        """Generate unittest imports."""
        return """import unittest"""

    def _junit_imports(self) -> str:
        """Generate JUnit imports."""
        return """import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import static org.junit.jupiter.api.Assertions.*;"""

    def _testng_imports(self) -> str:
        """Generate TestNG imports."""
        return """import org.testng.annotations.Test;
import org.testng.annotations.BeforeMethod;
import org.testng.annotations.AfterMethod;
import static org.testng.Assert.*;"""

    def _mocha_imports(self) -> str:
        """Generate Mocha imports."""
        return """import { describe, it, beforeEach, afterEach } from 'mocha';
import { expect } from 'chai';"""

    def generate_test_suite_wrapper(
        self,
        suite_name: str,
        test_content: str
    ) -> str:
        """
        Wrap test content in framework-specific suite structure.

        Args:
            suite_name: Name of test suite
            test_content: Test functions/methods

        Returns:
            Complete test suite code
        """
        if self.framework in [Framework.JEST, Framework.VITEST, Framework.MOCHA]:
            return f"""describe('{suite_name}', () => {{
{self._indent(test_content, 2)}
}});"""

        elif self.framework == Framework.PYTEST:
            return f"""class Test{self._to_class_name(suite_name)}:
    \"\"\"Test suite for {suite_name}.\"\"\"

{self._indent(test_content, 4)}"""

        elif self.framework == Framework.UNITTEST:
            return f"""class Test{self._to_class_name(suite_name)}(unittest.TestCase):
    \"\"\"Test suite for {suite_name}.\"\"\"

{self._indent(test_content, 4)}"""

        elif self.framework in [Framework.JUNIT, Framework.TESTNG]:
            return f"""public class {self._to_class_name(suite_name)}Test {{

{self._indent(test_content, 4)}
}}"""

        return test_content

    def generate_test_function(
        self,
        test_name: str,
        test_body: str,
        description: str = ""
    ) -> str:
        """
        Generate framework-specific test function.

        Args:
            test_name: Name of test
            test_body: Test body code
            description: Test description

        Returns:
            Complete test function
        """
        if self.framework == Framework.JEST:
            return self._jest_test(test_name, test_body, description)
        elif self.framework == Framework.VITEST:
            return self._vitest_test(test_name, test_body, description)
        elif self.framework == Framework.PYTEST:
            return self._pytest_test(test_name, test_body, description)
        elif self.framework == Framework.UNITTEST:
            return self._unittest_test(test_name, test_body, description)
        elif self.framework == Framework.JUNIT:
            return self._junit_test(test_name, test_body, description)
        elif self.framework == Framework.TESTNG:
            return self._testng_test(test_name, test_body, description)
        elif self.framework == Framework.MOCHA:
            return self._mocha_test(test_name, test_body, description)
        else:
            return ""

    def _jest_test(self, test_name: str, test_body: str, description: str) -> str:
        """Generate Jest test."""
        return f"""it('{test_name}', () => {{
  // {description}
{self._indent(test_body, 2)}
}});"""

    def _vitest_test(self, test_name: str, test_body: str, description: str) -> str:
        """Generate Vitest test."""
        return f"""it('{test_name}', () => {{
  // {description}
{self._indent(test_body, 2)}
}});"""

    def _pytest_test(self, test_name: str, test_body: str, description: str) -> str:
        """Generate Pytest test."""
        func_name = test_name.replace(' ', '_').replace('-', '_')
        return f"""def test_{func_name}(self):
    \"\"\"
    {description or test_name}
    \"\"\"
{self._indent(test_body, 4)}"""

    def _unittest_test(self, test_name: str, test_body: str, description: str) -> str:
        """Generate unittest test."""
        func_name = self._to_camel_case(test_name)
        return f"""def test_{func_name}(self):
    \"\"\"
    {description or test_name}
    \"\"\"
{self._indent(test_body, 4)}"""

    def _junit_test(self, test_name: str, test_body: str, description: str) -> str:
        """Generate JUnit test."""
        method_name = self._to_camel_case(test_name)
        return f"""@Test
public void test{method_name}() {{
    // {description}
{self._indent(test_body, 4)}
}}"""

    def _testng_test(self, test_name: str, test_body: str, description: str) -> str:
        """Generate TestNG test."""
        method_name = self._to_camel_case(test_name)
        return f"""@Test
public void test{method_name}() {{
    // {description}
{self._indent(test_body, 4)}
}}"""

    def _mocha_test(self, test_name: str, test_body: str, description: str) -> str:
        """Generate Mocha test."""
        return f"""it('{test_name}', () => {{
  // {description}
{self._indent(test_body, 2)}
}});"""

    def generate_assertion(
        self,
        actual: str,
        expected: str,
        assertion_type: str = "equals"
    ) -> str:
        """
        Generate framework-specific assertion.

        Args:
            actual: Actual value expression
            expected: Expected value expression
            assertion_type: Type of assertion (equals, not_equals, true, false, throws)

        Returns:
            Assertion statement
        """
        if self.framework in [Framework.JEST, Framework.VITEST]:
            return self._jest_assertion(actual, expected, assertion_type)
        elif self.framework in [Framework.PYTEST, Framework.UNITTEST]:
            return self._python_assertion(actual, expected, assertion_type)
        elif self.framework in [Framework.JUNIT, Framework.TESTNG]:
            return self._java_assertion(actual, expected, assertion_type)
        elif self.framework == Framework.MOCHA:
            return self._chai_assertion(actual, expected, assertion_type)
        else:
            return f"assert {actual} == {expected}"

    def _jest_assertion(self, actual: str, expected: str, assertion_type: str) -> str:
        """Generate Jest assertion."""
        if assertion_type == "equals":
            return f"expect({actual}).toBe({expected});"
        elif assertion_type == "not_equals":
            return f"expect({actual}).not.toBe({expected});"
        elif assertion_type == "true":
            return f"expect({actual}).toBe(true);"
        elif assertion_type == "false":
            return f"expect({actual}).toBe(false);"
        elif assertion_type == "throws":
            return f"expect(() => {actual}).toThrow();"
        else:
            return f"expect({actual}).toBe({expected});"

    def _python_assertion(self, actual: str, expected: str, assertion_type: str) -> str:
        """Generate Python assertion."""
        if assertion_type == "equals":
            return f"assert {actual} == {expected}"
        elif assertion_type == "not_equals":
            return f"assert {actual} != {expected}"
        elif assertion_type == "true":
            return f"assert {actual} is True"
        elif assertion_type == "false":
            return f"assert {actual} is False"
        elif assertion_type == "throws":
            return f"with pytest.raises(Exception):\n    {actual}"
        else:
            return f"assert {actual} == {expected}"

    def _java_assertion(self, actual: str, expected: str, assertion_type: str) -> str:
        """Generate Java assertion."""
        if assertion_type == "equals":
            return f"assertEquals({expected}, {actual});"
        elif assertion_type == "not_equals":
            return f"assertNotEquals({expected}, {actual});"
        elif assertion_type == "true":
            return f"assertTrue({actual});"
        elif assertion_type == "false":
            return f"assertFalse({actual});"
        elif assertion_type == "throws":
            return f"assertThrows(Exception.class, () -> {actual});"
        else:
            return f"assertEquals({expected}, {actual});"

    def _chai_assertion(self, actual: str, expected: str, assertion_type: str) -> str:
        """Generate Chai assertion."""
        if assertion_type == "equals":
            return f"expect({actual}).to.equal({expected});"
        elif assertion_type == "not_equals":
            return f"expect({actual}).to.not.equal({expected});"
        elif assertion_type == "true":
            return f"expect({actual}).to.be.true;"
        elif assertion_type == "false":
            return f"expect({actual}).to.be.false;"
        elif assertion_type == "throws":
            return f"expect(() => {actual}).to.throw();"
        else:
            return f"expect({actual}).to.equal({expected});"

    def generate_setup_teardown(
        self,
        setup_code: str = "",
        teardown_code: str = ""
    ) -> str:
        """Generate setup and teardown hooks."""
        result = []

        if self.framework in [Framework.JEST, Framework.VITEST, Framework.MOCHA]:
            if setup_code:
                result.append(f"""beforeEach(() => {{
{self._indent(setup_code, 2)}
}});""")
            if teardown_code:
                result.append(f"""afterEach(() => {{
{self._indent(teardown_code, 2)}
}});""")

        elif self.framework == Framework.PYTEST:
            if setup_code:
                result.append(f"""@pytest.fixture(autouse=True)
def setup_method(self):
{self._indent(setup_code, 4)}
    yield""")
            if teardown_code:
                result.append(f"""
{self._indent(teardown_code, 4)}""")

        elif self.framework == Framework.UNITTEST:
            if setup_code:
                result.append(f"""def setUp(self):
{self._indent(setup_code, 4)}""")
            if teardown_code:
                result.append(f"""def tearDown(self):
{self._indent(teardown_code, 4)}""")

        elif self.framework in [Framework.JUNIT, Framework.TESTNG]:
            annotation = "@BeforeEach" if self.framework == Framework.JUNIT else "@BeforeMethod"
            if setup_code:
                result.append(f"""{annotation}
public void setUp() {{
{self._indent(setup_code, 4)}
}}""")

            annotation = "@AfterEach" if self.framework == Framework.JUNIT else "@AfterMethod"
            if teardown_code:
                result.append(f"""{annotation}
public void tearDown() {{
{self._indent(teardown_code, 4)}
}}""")

        return "\n\n".join(result)

    def _indent(self, text: str, spaces: int) -> str:
        """Indent text by number of spaces."""
        indent = " " * spaces
        lines = text.split('\n')
        return '\n'.join(indent + line if line.strip() else line for line in lines)

    def _to_camel_case(self, text: str) -> str:
        """Convert text to camelCase."""
        words = text.replace('-', ' ').replace('_', ' ').split()
        if not words:
            return text
        return words[0].lower() + ''.join(word.capitalize() for word in words[1:])

    def _to_class_name(self, text: str) -> str:
        """Convert text to ClassName."""
        words = text.replace('-', ' ').replace('_', ' ').split()
        return ''.join(word.capitalize() for word in words)

    def detect_framework(self, code: str) -> Optional[Framework]:
        """
        Auto-detect testing framework from code.

        Args:
            code: Test code

        Returns:
            Detected framework or None
        """
        # Jest patterns
        if 'from \'@jest/globals\'' in code or '@jest/' in code:
            return Framework.JEST

        # Vitest patterns
        if 'from \'vitest\'' in code or 'import { vi }' in code:
            return Framework.VITEST

        # Pytest patterns
        if 'import pytest' in code or 'def test_' in code and 'pytest.fixture' in code:
            return Framework.PYTEST

        # Unittest patterns
        if 'import unittest' in code and 'unittest.TestCase' in code:
            return Framework.UNITTEST

        # JUnit patterns
        if '@Test' in code and 'import org.junit' in code:
            return Framework.JUNIT

        # TestNG patterns
        if '@Test' in code and 'import org.testng' in code:
            return Framework.TESTNG

        # Mocha patterns
        if 'from \'mocha\'' in code or ('describe(' in code and 'from \'chai\'' in code):
            return Framework.MOCHA

        return None


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Generate framework-specific test snippets and detect test frameworks."
    )
    parser.add_argument(
        "--framework",
        choices=[framework.value for framework in Framework],
        default=Framework.PYTEST.value,
    )
    parser.add_argument(
        "--language",
        choices=[language.value for language in Language],
        default=Language.PYTHON.value,
    )
    parser.add_argument(
        "--action",
        choices=["imports", "assertion", "test-function", "suite", "detect"],
        default="imports",
    )
    parser.add_argument("--test-name", default="should handle expected behavior")
    parser.add_argument("--test-body", default="assert result == expected")
    parser.add_argument("--description", default="")
    parser.add_argument("--suite-name", default="GeneratedSuite")
    parser.add_argument("--actual", default="result")
    parser.add_argument("--expected", default="expected")
    parser.add_argument(
        "--assertion-type",
        choices=["equals", "not_equals", "true", "false", "throws"],
        default="equals",
    )
    parser.add_argument("--code-file", help="Path to test code for --action detect.")
    parser.add_argument("--code", help="Inline test code for --action detect.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        adapter = FrameworkAdapter(Framework(args.framework), Language(args.language))
        if args.action == "imports":
            print(adapter.generate_imports())
        elif args.action == "assertion":
            print(adapter.generate_assertion(args.actual, args.expected, args.assertion_type))
        elif args.action == "test-function":
            print(adapter.generate_test_function(args.test_name, args.test_body, args.description))
        elif args.action == "suite":
            print(adapter.generate_test_suite_wrapper(args.suite_name, args.test_body))
        elif args.action == "detect":
            code = read_text(path=args.code_file, inline=args.code)
            detected = adapter.detect_framework(code)
            emit_json({"framework": detected.value if detected else "unknown"})
        return 0
    except (SkillCliError, ValueError, KeyError, TypeError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
