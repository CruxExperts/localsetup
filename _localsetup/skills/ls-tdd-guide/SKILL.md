---
name: ls-tdd-guide
description: Use when following a test-driven development workflow with test generation, coverage analysis, and multi-framework support.
metadata:
  version: "1.1"
compatibility: "Python 3.12+. Scripts in scripts/ follow framework tooling standard (input validation, actionable stderr). See [TOOLING_POLICY.md](../../docs/TOOLING_POLICY.md) and [INPUT_HARDENING_STANDARD.md](../../docs/INPUT_HARDENING_STANDARD.md)."
---

# TDD Guide

Test-driven development skill for generating tests, analyzing coverage, and guiding red-green-refactor workflows across Jest, Pytest, JUnit, and Vitest.

## Table of Contents

- [Capabilities](#capabilities)
- [Workflows](#workflows)
- [Tools](#tools)
- [Input Requirements](#input-requirements)
- [Limitations](#limitations)

---

## Capabilities

| Capability | Description |
|------------|-------------|
| Test Generation | Convert requirements or code into test cases with proper structure |
| Coverage Analysis | Parse LCOV/JSON/XML reports, identify gaps, prioritize fixes |
| TDD Workflow | Guide red-green-refactor cycles with validation |
| Framework Adapters | Generate tests for Jest, Pytest, JUnit, Vitest, Mocha |
| Quality Scoring | Assess test isolation, assertions, naming, detect test smells |
| Fixture Generation | Create realistic test data, mocks, and factories |

---

## Workflows

### Generate Tests from Code

1. Provide source code (TypeScript, JavaScript, Python, Java)
2. Specify target framework (Jest, Pytest, JUnit, Vitest)
3. Run `test_generator.py` with requirements
4. Review generated test stubs
5. **Validation:** Tests compile and cover happy path, error cases, edge cases

### Analyze Coverage Gaps

1. Generate coverage report from test runner (`npm test -- --coverage`)
2. Run `coverage_analyzer.py` on LCOV/JSON/XML report
3. Review prioritized gaps (P0/P1/P2)
4. Generate missing tests for uncovered paths
5. **Validation:** Coverage meets target threshold (typically 80%+)

### TDD New Feature

1. Write failing test first (RED)
2. Run `tdd_workflow.py --phase red` to validate
3. Implement minimal code to pass (GREEN)
4. Run `tdd_workflow.py --phase green` to validate
5. Refactor while keeping tests green (REFACTOR)
6. **Validation:** All tests pass after each cycle

---

## Tools

Scripts are both importable Python modules and command-line tools. Run examples from the skill root (`_localsetup/skills/ls-tdd-guide`) or adjust paths for your checkout.

| Tool | Purpose | Usage |
|------|---------|-------|
| `test_generator.py` | Generate test cases from requirements JSON | `python scripts/test_generator.py --input requirements.json --framework pytest --module auth` |
| `coverage_analyzer.py` | Parse and analyze coverage reports | `python scripts/coverage_analyzer.py --report lcov.info --threshold 80` |
| `tdd_workflow.py` | Guide red-green-refactor cycles | `python scripts/tdd_workflow.py --phase red --requirement "user can sign in"` |
| `framework_adapter.py` | Generate framework-specific snippets | `python scripts/framework_adapter.py --framework pytest --action imports` |
| `fixture_generator.py` | Generate test data and mocks | `python scripts/fixture_generator.py mock-data --schema-file schema.json --count 5` |
| `metrics_calculator.py` | Calculate test quality metrics | `python scripts/metrics_calculator.py --source app.py --tests test_app.py` |
| `format_detector.py` | Detect language and framework | `python scripts/format_detector.py --file source.ts` |
| `output_formatter.py` | Format JSON output for CLI/desktop/API | `python scripts/output_formatter.py --kind coverage --input summary.json` |

---

## Input Requirements

**For Test Generation:**
- Source code (file path or pasted content)
- Target framework (Jest, Pytest, JUnit, Vitest)
- Coverage scope (unit, integration, edge cases)

**For Coverage Analysis:**
- Coverage report file (LCOV, JSON, or XML format)
- Optional: Source code for context
- Optional: Target threshold percentage

**For TDD Workflow:**
- Feature requirements or user story
- Current phase (RED, GREEN, REFACTOR)
- Test code and implementation status

---

## Limitations

| Scope | Details |
|-------|---------|
| Unit test focus | Integration and E2E tests require different patterns |
| Static analysis | Cannot execute tests or measure runtime behavior |
| Language support | Best for TypeScript, JavaScript, Python, Java |
| Report formats | LCOV, JSON, XML only; other formats need conversion |
| Generated tests | Provide scaffolding; require human review for complex logic |

**When to use other tools:**
- E2E testing: Playwright, Cypress, Selenium
- Performance testing: k6, JMeter, Locust
- Security testing: OWASP ZAP, Burp Suite
