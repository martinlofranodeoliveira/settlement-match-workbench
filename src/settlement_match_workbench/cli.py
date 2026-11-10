"""Bounded local I/O adapter; complete financial report bytes remain SDK-owned."""
import argparse
from importlib import metadata, resources
import json
import os
import stat
import sys

from .financial import ReportResult, analyze_json
from .types import Limits, Status

_RAW_CAP = 524288
_OUTPUT_CAP = 524288
_WORK_CAP = 100000000
_DEFAULT_WORK = 50000000
_EXITS = {Status.COMPLETE: 0, Status.INVALID_INPUT: 2,
          Status.UNKNOWN_BUDGET: 4, Status.INTERNAL_ERROR: 5}


class _UsageError(Exception):
    pass


class _InputError(Exception):
    pass


class _OutputError(Exception):
    pass


class _EarlyExit(Exception):
    pass


def _quiet_failed_fd(stream):
    """Only silence a descriptor whose actual write/flush has already failed."""
    try:
        fd = stream.fileno()
        if fd not in (1, 2):
            return
        null_fd = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
        try:
            os.dup2(null_fd, fd)
        finally:
            if null_fd != fd:
                os.close(null_fd)
    except (AttributeError, OSError, ValueError):
        pass


def _write(stream, data):
    try:
        binary = stream.buffer
        offset = 0
        while offset < len(data):
            written = binary.write(memoryview(data)[offset:])
            if type(written) is not int or written <= 0 or written > len(data) - offset:
                raise OSError('stream made no valid progress')
            offset += written
        binary.flush()
    except (AttributeError, OSError, TypeError, ValueError):
        _quiet_failed_fd(stream)
        raise _OutputError() from None


def _failure(status, code, work=0):
    # Failure frames only. There is no adapter serializer for caller analysis.
    return json.dumps({'schema_version': 1, 'status': status.value, 'code': code,
                       'work_used': work, 'analysis': None}, ensure_ascii=True,
                      sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'


def _diagnostic(data, primary_exit):
    try:
        _write(sys.stderr, data)
    except _OutputError:
        pass
    return primary_exit


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise _UsageError()

    def exit(self, status=0, message=None):
        if status:
            raise _UsageError()
        raise _EarlyExit()

    def _print_message(self, message, file=None):
        if message:
            _write(sys.stderr if file is None else file, message.encode('utf-8'))


def _number(text, ceiling):
    if (type(text) is not str or not text or len(text) > len(str(ceiling))
            or not text.isascii() or not text.isdecimal()
            or (len(text) > 1 and text[0] == '0')):
        raise argparse.ArgumentTypeError('bounded canonical integer required')
    value = int(text)
    if value > ceiling:
        raise argparse.ArgumentTypeError('bounded canonical integer required')
    return value


def _arguments(argv):
    if type(argv) not in (list, tuple) or any(type(v) is not str for v in argv):
        raise _UsageError()
    for option in ('--input', '--max-work', '--max-output-bytes', '--assert'):
        if sum(token.split('=', 1)[0] == option for token in argv) > 1:
            raise _UsageError()
    if '--help' in argv and list(argv) not in (['--help'], ['analyze', '--help'], ['demo', '--help']):
        raise _UsageError()
    if '--version' in argv and list(argv) != ['--version']:
        raise _UsageError()
    parser = _Parser(prog='settlement-match-workbench', allow_abbrev=False, add_help=False,
                     description='Explain optimal assignments for bounded synthetic settlement inputs.')
    parser.add_argument('--help', action='help', help='show this help and exit')
    parser.add_argument('--version', action='version', version='settlement-match-workbench ' + metadata.version('settlement-match-workbench'))
    commands = parser.add_subparsers(dest='command', required=True, parser_class=_Parser)
    analyze = commands.add_parser('analyze', allow_abbrev=False, add_help=False,
                                  help='analyze one local synthetic input JSON document')
    analyze.add_argument('--input', required=True, metavar='FILE|-')
    demo = commands.add_parser('demo', allow_abbrev=False, add_help=False,
                               help='run the packaged independent synthetic example')
    demo.add_argument('--assert', dest='verify', action='store_true', help='check the complete independent expected Analysis')
    for child in (analyze, demo):
        child.add_argument('--help', action='help', help='show this help and exit')
        child.add_argument('--max-work', default=_DEFAULT_WORK,
                           type=lambda value: _number(value, _WORK_CAP), metavar='N')
        child.add_argument('--max-output-bytes', default=_OUTPUT_CAP,
                           type=lambda value: _number(value, _OUTPUT_CAP), metavar='N')
    return parser.parse_args(argv)


def _read_bounded(read):
    parts = []
    total = 0
    while total <= _RAW_CAP:
        chunk = read(min(65536, _RAW_CAP + 1 - total))
        if type(chunk) is not bytes:
            raise _InputError()
        if not chunk:
            break
        total += len(chunk)
        if total > _RAW_CAP + 1:
            raise _InputError()
        parts.append(chunk)
    return b''.join(parts)


def _snapshot(st):
    return (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode), st.st_size,
            st.st_mtime_ns, st.st_ctime_ns)


def _read_input(path):
    try:
        if path == '-':
            return _read_bounded(sys.stdin.buffer.read)
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise _InputError()
            raw = _read_bounded(lambda size: os.read(fd, size))
            after = os.fstat(fd)
            if _snapshot(before) != _snapshot(after):
                raise _InputError()
            return raw
        finally:
            os.close(fd)
    except (AttributeError, OSError, ValueError):
        raise _InputError() from None


def main(argv=None):
    work = 0
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
        if args.command == 'analyze':
            raw = _read_input(args.input)
        else:
            raw = resources.files('settlement_match_workbench').joinpath('data/demo-input.json').read_bytes()
        result = analyze_json(raw, Limits(args.max_work))
        if type(result) is not ReportResult or type(result.status) is not Status:
            raise RuntimeError('invalid internal result')
        work = result.work_used
        if result.status is not Status.COMPLETE:
            return _diagnostic(result.json_bytes, _EXITS[result.status])
        if args.command == 'demo' and args.verify:
            expected = json.loads(resources.files('settlement_match_workbench').joinpath('data/demo-analysis.json').read_bytes())
            actual = json.loads(result.json_bytes)
            canonical = json.dumps(actual, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'
            if actual['analysis'] != expected or canonical != result.json_bytes:
                raise RuntimeError('synthetic demo mismatch')
        if len(result.json_bytes) > args.max_output_bytes:
            return _diagnostic(_failure(Status.UNKNOWN_BUDGET, 'CLI_OUTPUT_BYTES', work), 4)
        _write(sys.stdout, result.json_bytes)
        return 0
    except _EarlyExit:
        return 0
    except _UsageError:
        return _diagnostic(_failure(Status.INVALID_INPUT, 'CLI_USAGE'), 2)
    except _InputError:
        return _diagnostic(_failure(Status.INTERNAL_ERROR, 'INPUT_IO'), 3)
    except _OutputError:
        return _diagnostic(_failure(Status.INTERNAL_ERROR, 'OUTPUT_IO', work), 3)
    except Exception:
        return _diagnostic(_failure(Status.INTERNAL_ERROR, 'CLI_INTERNAL', work), 5)
