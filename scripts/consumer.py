"""Independent artifact-only consumer, not a source checkout or optimizer."""
import copy
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import subprocess

import settlement_match_workbench as core
from settlement_match_workbench import financial

CHECKS = 0
ROOT = Path('/checks')


def require(condition, label):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(label)


def load(name):
    return json.loads((ROOT / name).read_bytes())


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def report(value, limits=core.Limits()):
    result = financial.analyze_json(canonical(value), limits)
    require(result.status is core.Status.COMPLETE and result.code == 'OK', 'complete financial result')
    frame = json.loads(result.json_bytes)
    require(set(frame) == {'schema_version', 'status', 'code', 'work_used', 'analysis'}, 'closed report frame')
    require(result.json_bytes == canonical(frame) + b'\n', 'canonical frame and final LF')
    require(len(result.json_bytes) <= 524288 and result.work_used <= limits.max_work, 'complete report bounds')
    return result, frame['analysis']


def main():
    require(platform.python_version() == '3.13.18', 'qualified runtime version')
    prefix = Path(sys.prefix)
    require(prefix == Path('/opt/settlement-runtime'), 'cold runtime virtual environment')
    dist = metadata.distribution('settlement-match-workbench')
    require(dist.version == '0.1.0' and not dist.requires, 'installed package metadata')
    for name in ('setuptools', 'wheel', 'packaging'):
        try:
            metadata.distribution(name)
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError('build backend leaked into runtime')
        require(True, 'build dependency absent')
    for name in ('cc', 'gcc', 'g++', 'clang', 'make'):
        require(shutil.which(name) is None, 'compiler absent')
    expected = load('module-hashes.json')
    for name, digest in expected.items():
        path = Path(dist.locate_file(name)).resolve()
        require(path.is_relative_to(prefix), 'module installed in clean runtime')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'installed module source bytes')
    files = list(dist.files)
    metadata_roots = [str(p).rsplit('/', 1)[0] for p in files if str(p).count('/') == 1 and str(p).endswith('.dist-info/METADATA')]
    require(len(metadata_roots) == 1, 'one installed metadata root')
    license_root = metadata_roots[0] + '/licenses/'
    notices = load('license-hashes.json')
    for name, digest in notices.items():
        require(hashlib.sha256(Path(dist.locate_file(license_root + name)).read_bytes()).hexdigest() == digest, 'installed genuine notice bytes')

    literals = load('hand-literal-graphs.compact.json')['cases']
    require(len(literals) == 20, 'independent literal family count')
    for case in literals:
        problem = core.Problem(tuple(case['left_ids']), tuple(case['right_ids']), tuple(core.Edge(**e) for e in case['edges']))
        result = core.solve(problem)
        require(result.status is core.Status.COMPLETE, 'literal graph complete')
        analysis = result.analysis
        truth = case['expected']
        require((analysis.objective.cardinality, analysis.objective.cost) == (truth['cardinality'], truth['cost']), 'literal exact objective')
        representative = sorted(p.left_id + ':' + p.right_id for p in analysis.representative)
        require(representative in truth['optimal_matchings'], 'representative in literal optimal family')
        for field, value in (('forced', 'FORCED'), ('optional', 'OPTIONAL'), ('globally_excluded', 'GLOBALLY_EXCLUDED')):
            require(sorted(e.left_id + ':' + e.right_id for e in analysis.edges if e.classification.value == value) == sorted(truth[field]), 'all-optima literal edge classes')
        for vertices, expected_free in ((analysis.left, truth['left_can_be_unmatched']), (analysis.right, truth['right_can_be_unmatched'])):
            require({v.id: v.can_be_unmatched for v in vertices} == expected_free, 'literal free-vertex facts')

    value = load('unique-input.json')
    real, analysis = report(value)
    require(analysis == load('unique-analysis.json'), 'entire independent financial Analysis')
    at_limit, same = report(value, core.Limits(real.work_used))
    require(same == analysis, 'observed complete work boundary')
    short = financial.analyze_json(canonical(value), core.Limits(real.work_used - 1))
    require(short.status is core.Status.UNKNOWN_BUDGET and short.code == 'WORK_LIMIT', 'one-less global work boundary')
    require(json.loads(short.json_bytes)['analysis'] is None, 'no result prefix on logical exhaustion')
    zero = financial.analyze_json(canonical(value), core.Limits(0))
    require(zero.status is core.Status.UNKNOWN_BUDGET and zero.work_used == 0, 'zero work budget')
    duplicate = financial.analyze_json(b'{"schema_version":1,"schema_version":1}', core.Limits(0))
    require(duplicate.status is core.Status.INVALID_INPUT and duplicate.code == 'JSON_DUPLICATE' and duplicate.work_used == 0, 'decoded duplicate admission before work')

    small = {
        'schema_version': 1, 'scenario_id': 'cold',
        'currencies': [{'code': 'BRL', 'minor_digits': 2}, {'code': 'USD', 'minor_digits': 2}],
        'policy': {'early_days': 31, 'late_days': 31},
        'lots': [{'id': 'L%02d' % i, 'currency': 'BRL' if i < 8 else 'USD', 'expected_on': '2026-11-10', 'gross_minor': '9000', 'fees_minor': '0', 'refunds_minor': '0', 'reference': None} for i in range(16)],
        'credits': [{'id': 'C%02d' % i, 'currency': 'BRL' if i < 8 else 'USD', 'booked_on': '2026-12-11', 'amount_minor': '9000', 'reference': None} for i in range(16)],
    }
    maximum, a = report(small, core.Limits(100_000_000))
    require(a['objective'] == {'cardinality': 16, 'cost': 8448}, '16x16 exact scalarization objective')
    candidates = [p for p in a['pairs'] if not p['rejection_reasons']]
    require(len(a['pairs']) == 256 and len(candidates) == 128, 'complete pair and candidate coverage')
    require({p['candidate_cost'] for p in candidates} == {528}, 'reference-priority scalar cost')
    require({p['classification'] for p in candidates} == {'OPTIONAL'}, 'all128 candidate edges optional')
    require(all(not v['can_be_unmatched'] for v in a['lots'] + a['credits']), 'all32 vertices always matched')
    require(all(t['forced_pair_minor'] == '0' and t['unresolved_lot_minor'] == '72000' and t['unresolved_credit_minor'] == '72000' for t in a['totals_by_currency']), 'ambiguous totals are not reconciled totals')
    cap = copy.deepcopy(small)
    cap['currencies'] = [{'code': 'BRL', 'minor_digits': 2}]
    for row in cap['lots'] + cap['credits']:
        row['currency'] = 'BRL'
    rejected = financial.analyze_json(canonical(cap), core.Limits(0))
    require(rejected.status is core.Status.INVALID_INPUT and rejected.code == 'CANDIDATE_LIMIT' and rejected.work_used == 0, 'candidate overflow is refused, not truncated')
    require(json.loads(rejected.json_bytes)['analysis'] is None, 'candidate overflow has no Analysis')
    aggregate = copy.deepcopy(small)
    aggregate['currencies'] = [{'code': 'BRL', 'minor_digits': 2}]
    aggregate['credits'] = []
    for row in aggregate['lots']:
        row['currency'] = 'BRL'
        row['gross_minor'] = '1000000000000000'
    _, a = report(aggregate)
    require(a['totals_by_currency'][0]['net_minor'] == '16000000000000000', '17-digit aggregate remains an exact decimal string')
    cli = '/opt/settlement-runtime/bin/settlement-match-workbench'
    for args in (['demo', '--assert'], ['analyze', '--input', '/checks/unique-input.json']):
        child = subprocess.run([cli, *args], capture_output=True, timeout=15)
        require(child.returncode == 0 and child.stdout == real.json_bytes and child.stderr == b'', 'actual installed CLI preserves SDK bytes')
    child = subprocess.run([sys.executable, '-I', '-B', '-O', '-m', 'settlement_match_workbench', 'demo', '--assert'], capture_output=True, timeout=15)
    require(child.returncode == 0 and child.stdout == real.json_bytes and child.stderr == b'', 'installed asserting demo under -O')
    child = subprocess.run([cli, 'analyze', '--input', '/checks/unique-input.json', '--max-output-bytes', '0'], capture_output=True, timeout=15)
    require(child.returncode == 4 and child.stdout == b'' and json.loads(child.stderr)['code'] == 'CLI_OUTPUT_BYTES', 'installed CLI output budget')
    print(json.dumps({'status': 'PASS_ARTIFACT_ONLY_CONSUMER', 'checks': CHECKS, 'python': platform.python_version(), 'installed_payload_files': len(expected), 'python_modules': sum(name.endswith('.py') for name in expected), 'installed_license_files': len(notices), 'literal_graphs': len(literals), 'financial_unique': {'work_used': real.work_used, 'bytes': len(real.json_bytes)}, 'financial_16x16_128edges': {'work_used': maximum.work_used, 'bytes': len(maximum.json_bytes)}, 'limits': 'version/fixture observations; no universal performance guarantee'}))


if __name__ == '__main__':
    main()
