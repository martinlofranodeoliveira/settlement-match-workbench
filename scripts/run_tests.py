"""Run real unittest methods against the installed wheel; reject empty/skipped suites."""
import importlib
import json
from pathlib import Path
import sys
import unittest


def main():
    tests, output = map(Path, sys.argv[1:3])
    module = importlib.import_module("settlement_match_workbench")
    origin = Path(module.__file__).resolve()
    prefix = Path(sys.prefix).resolve()
    if not origin.is_relative_to(prefix) or "site-packages" not in origin.parts:
        raise AssertionError("tests must import the installed package")
    suite = unittest.defaultTestLoader.discover(str(tests), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    record = {
        "framework": "unittest",
        "python": sys.version.split()[0],
        "package_origin": str(origin),
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "unexpected_successes": len(result.unexpectedSuccesses),
    }
    output.write_text(json.dumps(record, indent=2) + "\n")
    return 0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
