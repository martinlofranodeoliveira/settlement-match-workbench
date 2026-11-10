"""Compare the exact caller-mounted source to the baked image before/after gates."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_gate import inventory


def main():
    mode, source_text = sys.argv[1:3]
    source = Path(source_text)
    expected = json.loads(Path('/opt/qualification/source-inventory.json').read_text())
    if inventory(source) != expected:
        raise AssertionError('mounted source differs from baked inventory')
    if mode == 'sdk':
        with tempfile.TemporaryDirectory(prefix='settlement-quality-') as scratch:
            out = Path(scratch) / 'distributions'; out.mkdir()
            evidence = Path(scratch) / 'evidence'; evidence.mkdir()
            subprocess.run([sys.executable, '-I', '-B', '/opt/settlement-checks/package_gate.py', str(source), str(out), str(evidence)], check=True)
    elif mode == 'runtime':
        subprocess.run(['/opt/settlement-runtime/bin/python', '-I', '-B', '/checks/consumer.py'], check=True)
    else:
        raise ValueError('unknown gate')
    if inventory(source) != expected:
        raise AssertionError('mounted source changed during gate')
    print(json.dumps({'status': 'PASS', 'gate': mode, 'source_sha256': expected['sha256']}))


if __name__ == '__main__':
    main()
