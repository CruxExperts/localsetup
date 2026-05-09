# TDD Guide Overview

This reference is the concise map for `ls-tdd-guide`. The authoritative entry point is `SKILL.md`; deeper guidance lives in the focused references:

- `how-to-use.md` for prompt patterns and workflow examples.
- `framework-guide.md` for Jest, Vitest, Pytest, JUnit, and Mocha conventions.
- `ci-integration.md` for coverage gates and CI examples.
- `tdd-best-practices.md` for red-green-refactor habits and quality checks.

## Contract

The skill ships Python scripts under `scripts/`. Each script can be imported as a library module and can also be run from the command line with `--help`.

Run commands from the skill root:

```bash
python scripts/format_detector.py --help
python scripts/test_generator.py --help
python scripts/coverage_analyzer.py --help
python scripts/tdd_workflow.py --help
```

## Common Flows

### Detect Input Format

```bash
python scripts/format_detector.py --file path/to/source.py
```

Outputs JSON with detected content type, language, framework, and report format.

### Generate Tests

Create a requirements JSON file with keys such as `user_stories`, `acceptance_criteria`, or `api_specs`, then run:

```bash
python scripts/test_generator.py --input requirements.json --framework pytest --module auth
```

Without `--module`, the tool emits JSON test-case specs. With `--module`, it emits a framework-specific test file scaffold.

### Analyze Coverage

```bash
python scripts/coverage_analyzer.py --report coverage/lcov.info --threshold 80
```

The analyzer supports LCOV, Istanbul-style JSON, and Cobertura-style XML. Invalid JSON and XML inputs fail with explicit errors instead of being ignored.

### Validate A TDD Phase

```bash
python scripts/tdd_workflow.py --phase red --test-code-file tests/test_auth.py --test-result-json '{"status":"failed"}'
```

Use `--phase green` with implementation code and a passing test result, or `--phase refactor` with original/refactored code plus test results.

### Generate Fixtures

```bash
python scripts/fixture_generator.py mock-data --schema-file schema.json --count 5
python scripts/fixture_generator.py fixture --name user --data-file user.json --format yaml
```

YAML output uses PyYAML (`yaml.safe_dump`) per the framework tooling policy.

## Script Index

| Script | Library Class | CLI Role |
|--------|---------------|----------|
| `test_generator.py` | `TestGenerator` | Generate test-case specs or test files |
| `coverage_analyzer.py` | `CoverageAnalyzer` | Parse reports, summarize coverage, find gaps |
| `metrics_calculator.py` | `MetricsCalculator` | Calculate complexity, test quality, and execution metrics |
| `framework_adapter.py` | `FrameworkAdapter` | Generate framework imports, assertions, functions, and suites |
| `tdd_workflow.py` | `TDDWorkflow` | Validate red, green, and refactor phases |
| `fixture_generator.py` | `FixtureGenerator` | Generate boundaries, edge cases, mock data, and fixtures |
| `format_detector.py` | `FormatDetector` | Detect language, framework, coverage format, or project structure |
| `output_formatter.py` | `OutputFormatter` | Format JSON payloads for terminal, markdown, or API use |

## Maintenance Notes

- Keep examples aligned with actual argparse options.
- Keep this file brief; add detailed material to the focused references instead.
- Do not reintroduce custom YAML serialization. Use PyYAML for YAML output.
