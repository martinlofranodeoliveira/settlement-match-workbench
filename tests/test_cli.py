"""Independent CLI tests finalized before any CLI implementation was written.

The financial/core SDK already exists. These are Codex support tests, not model
tests. Controlled Python I/O seams are labelled; /dev/full and pipes are real OS
faults. No test claims physical stdout atomicity or an unobserved prefix.
"""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from settlement_match_workbench import Limits
from settlement_match_workbench.financial import analyze_json

DATA = Path(__file__).resolve().parents[1] / 'fixtures'
RAW = (DATA / 'unique-input.json').read_bytes()


def frame(value):
    return json.loads(value)


def call(args, raw=None, **kwargs):
    return subprocess.run([sys.executable, '-I', '-B', '-m', 'settlement_match_workbench', *args],
                          input=raw, stdout=kwargs.pop('stdout', subprocess.PIPE),
                          stderr=kwargs.pop('stderr', subprocess.PIPE), timeout=15, **kwargs)


class CliTests(unittest.TestCase):
    def diagnostic(self, raw, code, status):
        value = frame(raw)
        self.assertEqual(set(value), {'schema_version', 'status', 'code', 'work_used', 'analysis'})
        self.assertEqual(value['schema_version'], 1)
        self.assertEqual(value['status'], status)
        self.assertEqual(value['code'], code)
        self.assertIsNone(value['analysis'])
        self.assertEqual(raw, json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n')
        return value

    def direct(self, args, stdin=None):
        from settlement_match_workbench import cli
        stdout, stderr = io.BytesIO(), io.BytesIO()
        out = types.SimpleNamespace(buffer=stdout, flush=stdout.flush)
        err = types.SimpleNamespace(buffer=stderr, flush=stderr.flush)
        patches = [patch.object(sys, 'stdout', out), patch.object(sys, 'stderr', err)]
        if stdin is not None:
            patches.append(patch.object(sys, 'stdin', types.SimpleNamespace(buffer=stdin)))
        for item in patches: item.start()
        try:
            code = cli.main(args)
        finally:
            for item in reversed(patches): item.stop()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_analyze_stdin_preserves_exact_sdk_bytes(self):
        result = call(['analyze', '--input', '-'], RAW)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b'')
        self.assertEqual(result.stdout, analyze_json(RAW).json_bytes)
        self.assertEqual(frame(result.stdout)['analysis'], json.loads((DATA / 'unique-analysis.json').read_bytes()))

    def test_regular_shared_readable_file_symlink_and_nonregular(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); original = root / 'input.json'; original.write_bytes(RAW); original.chmod(0o444)
            link = root / 'link.json'; link.symlink_to(original)
            for path in (original, link, DATA / 'unique-input.json'):
                with self.subTest(path=path.name):
                    result = call(['analyze', '--input', str(path)])
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, analyze_json(RAW).json_bytes)
            fifo = root / 'input.fifo'; os.mkfifo(fifo)
            for path in (fifo, root, root / 'SENSITIVE_MISSING_PATH'):
                with self.subTest(kind=path.name):
                    result = call(['analyze', '--input', str(path)])
                    self.assertEqual(result.returncode, 3)
                    self.assertEqual(result.stdout, b'')
                    self.diagnostic(result.stderr, 'INPUT_IO', 'INTERNAL_ERROR')
                    self.assertNotIn(b'SENSITIVE', result.stderr)

    def test_exact_raw_byte_cap_and_one_more(self):
        padded = RAW + b' ' * (524288 - len(RAW))
        self.assertEqual(call(['analyze', '--input', '-'], padded).stdout, analyze_json(RAW).json_bytes)
        result = call(['analyze', '--input', '-', '--max-output-bytes', '0'], padded + b' ')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b'')
        self.diagnostic(result.stderr, 'SIZE', 'INVALID_INPUT')

    def test_open_nonblocking_pipe_json_prefix_is_not_eof(self):
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        try:
            os.write(write_fd, RAW)
            child = subprocess.Popen([sys.executable, '-I', '-B', '-m', 'settlement_match_workbench', 'analyze', '--input', '-'], stdin=read_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 3)
            self.assertEqual(stdout, b'')
            self.diagnostic(stderr, 'INPUT_IO', 'INTERNAL_ERROR')
        finally:
            os.close(read_fd); os.close(write_fd)

    def test_controlled_stdin_none_after_positive_prefix(self):
        class Reader:
            def __init__(self): self.calls = 0
            def read(self, _size):
                self.calls += 1
                return RAW if self.calls == 1 else None
        code, stdout, stderr = self.direct(['analyze', '--input', '-'], Reader())
        self.assertEqual(code, 3)
        self.assertEqual(stdout, b'')
        self.diagnostic(stderr, 'INPUT_IO', 'INTERNAL_ERROR')

    def test_output_cap_exact_one_less_and_zero_includes_lf(self):
        expected = analyze_json(RAW)
        result = call(['analyze', '--input', '-', '--max-output-bytes', str(len(expected.json_bytes))], RAW)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected.json_bytes, b''))
        for cap in (0, len(expected.json_bytes) - 1):
            with self.subTest(cap=cap):
                result = call(['analyze', '--input', '-', '--max-output-bytes', str(cap)], RAW)
                self.assertEqual((result.returncode, result.stdout), (4, b''))
                self.assertEqual(self.diagnostic(result.stderr, 'CLI_OUTPUT_BYTES', 'UNKNOWN_BUDGET')['work_used'], expected.work_used)
        result = call(['analyze', '--input', '-', '--max-work', '0', '--max-output-bytes', '0'], RAW)
        self.assertEqual((result.returncode, result.stdout), (4, b''))
        self.diagnostic(result.stderr, 'WORK_LIMIT', 'UNKNOWN_BUDGET')
        result = call(['analyze', '--input', '-', '--max-output-bytes', '0'], b'{')
        self.assertEqual((result.returncode, result.stdout), (2, b''))
        self.diagnostic(result.stderr, 'JSON_SYNTAX', 'INVALID_INPUT')

    def test_closed_usage_rejects_abbreviation_duplicates_and_numeric_coercion(self):
        cases = [[], ['analyze'], ['analyze', '--inp', '-'], ['demo', '--input', '-'], ['SENSITIVE_UNKNOWN'], ['analyze', '--input', '-', '--input', '-']]
        cases += [['analyze', '--input', '-', '--max-work', value] for value in ('-1', '+1', '01', '1e0', '100000001', '9' * 128)]
        cases += [['demo', '--max-work', '0', '--max-work', '0'], ['demo', '--max-output-bytes', '524289'], ['demo', '--assert', '--assert']]
        for args in cases:
            with self.subTest(args=args[:3]):
                result = call(args, b'')
                self.assertEqual((result.returncode, result.stdout), (2, b''))
                self.diagnostic(result.stderr, 'CLI_USAGE', 'INVALID_INPUT')
                self.assertNotIn(b'SENSITIVE', result.stderr)

    def test_demo_help_version_ignore_non_eof_stdin_and_assert_under_O(self):
        for args, optimized in [(['demo', '--assert'], False), (['demo', '--assert'], True), (['--help'], False), (['--version'], False)]:
            with self.subTest(args=args, optimized=optimized):
                argv = [sys.executable, '-I', '-B'] + (['-O'] if optimized else []) + ['-m', 'settlement_match_workbench', *args]
                child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    child.wait(timeout=10)
                    stdout, stderr = child.stdout.read(), child.stderr.read()
                    self.assertEqual((child.returncode, stderr), (0, b''))
                    self.assertTrue(stdout.endswith(b'\n'))
                    if args[0] == 'demo':
                        self.assertEqual(frame(stdout)['analysis'], json.loads((DATA / 'unique-analysis.json').read_bytes()))
                    else:
                        self.assertNotIn(b'Traceback', stdout)
                finally:
                    child.stdin.close(); child.stdout.close(); child.stderr.close()

    def test_dev_full_stdout_help_version_demo_and_both(self):
        for args, raw in [(['--help'], None), (['--version'], None), (['demo', '--assert'], None), (['analyze', '--input', '-'], RAW)]:
            with self.subTest(command=args[0]):
                with open('/dev/full', 'wb', buffering=0) as full:
                    result = call(args, raw, stdout=full)
                self.assertEqual(result.returncode, 3)
                self.diagnostic(result.stderr, 'OUTPUT_IO', 'INTERNAL_ERROR')
        with open('/dev/full', 'wb', buffering=0) as full:
            result = call(['demo', '--assert'], stdout=full, stderr=full)
        self.assertEqual(result.returncode, 3)

    def test_failed_stderr_preserves_primary_invalid_and_unknown(self):
        for args, raw, expected in [(['SENSITIVE'], None, 2), (['analyze', '--input', '-'], b'{', 2), (['analyze', '--input', '-', '--max-work', '0'], RAW, 4)]:
            with self.subTest(expected=expected, command=args[0]):
                with open('/dev/full', 'wb', buffering=0) as full:
                    result = call(args, raw, stderr=full)
                self.assertEqual(result.returncode, expected)
                self.assertEqual(result.stdout, b'')

    def test_real_closed_stdout_pipe_is_controlled_io_not_finalizer120(self):
        read_fd, write_fd = os.pipe(); os.close(read_fd)
        try:
            result = call(['demo', '--assert'], stdout=write_fd)
            self.assertEqual(result.returncode, 3)
            self.diagnostic(result.stderr, 'OUTPUT_IO', 'INTERNAL_ERROR')
        finally:
            os.close(write_fd)

    def test_controlled_unexpected_adapter_error_does_not_echo_text(self):
        from settlement_match_workbench import cli
        with patch.object(cli, 'analyze_json', side_effect=RuntimeError('SENSITIVE_SDK_DETAIL')):
            code, stdout, stderr = self.direct(['analyze', '--input', '-'], io.BytesIO(RAW))
        self.assertEqual((code, stdout), (5, b''))
        self.diagnostic(stderr, 'CLI_INTERNAL', 'INTERNAL_ERROR')
        self.assertNotIn(b'SENSITIVE', stderr)

    def test_same_open_descriptor_survives_path_replacement_controlled_seam(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'chosen.json'; path.write_bytes(RAW)
            original_open = os.open
            def replace_after_open(name, flags, *args, **kwargs):
                fd = original_open(name, flags, *args, **kwargs)
                if os.fspath(name) == str(path):
                    path.rename(path.with_suffix('.old'))
                    path.write_bytes(b'{')
                return fd
            with patch.object(os, 'open', side_effect=replace_after_open):
                code, stdout, stderr = self.direct(['analyze', '--input', str(path)])
            self.assertEqual((code, stdout, stderr), (0, analyze_json(RAW).json_bytes, b''))
