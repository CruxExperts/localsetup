"""Bounded diagnostic output, independent of provider initialization."""
import json
import threading
import time

from ..branding import CLI_NAME, PRODUCT_NAME
from .run_io import Streams, safe


def emit(report: dict, format: str) -> None:
    if format == 'json':
        output = json.dumps(report, sort_keys=True, ensure_ascii=True) + '\n'
    else:
        rows = [f"{CLI_NAME} ({PRODUCT_NAME}) {report['framework_version']}",
                f"Static checks: {report['status']}; SDK payload: {report['sdk_payload']}",
                f"Runtime: {report['runtime']['status']}; profiles: {report['profiles']['status']}",
                'Dependencies: ' + report['runtime'].get('dependencies', {}).get('status', 'unavailable'),
                'Native sandbox: ' + report['runtime'].get('native_sandbox', {}).get('status', 'unavailable'),
                'Execution: requires per-run preflight']
        rows.extend('- ' + issue for issue in report['issues'])
        rows.extend(name + ': ' + json.dumps(path, ensure_ascii=True)
                    for name, path in report['locations'].items())
        output = safe('\n'.join(rows)) + '\n'
    Streams(time.monotonic() + 5, threading.Event()).write(output)
