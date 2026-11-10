#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
mode=${1:-all}
case "$mode" in all|prepare|test|demo) ;; *) printf '%s\n' 'usage: sh scripts/check.sh [all|prepare|test|demo]' >&2; exit 2;; esac
if [ "$#" -gt 1 ]; then printf '%s\n' 'unexpected arguments' >&2; exit 2; fi
prepared=settlement-match-dependencies:local
sdk_container=''
runtime_container=''
gate_context=''
cleanup() {
    if [ -n "$sdk_container" ]; then docker rm -f "$sdk_container" >/dev/null 2>&1 || true; fi
    if [ -n "$runtime_container" ]; then docker rm -f "$runtime_container" >/dev/null 2>&1 || true; fi
    if [ -n "$gate_context" ]; then rm -rf -- "$gate_context"; fi
}
trap cleanup EXIT HUP INT TERM
invalidate_dist() {
    if [ -L "$project_dir/dist" ] || { [ -e "$project_dir/dist" ] && [ ! -d "$project_dir/dist" ]; }; then
        printf '%s\n' 'dist must be a real generated directory' >&2
        exit 1
    fi
    rm -rf -- "$project_dir/dist"
}
inspect_owned() {
    docker inspect -f '{"image":{{json .Image}},"user":{{json .Config.User}},"entrypoint":{{json .Config.Entrypoint}},"network":{{json .HostConfig.NetworkMode}},"binds":{{json .HostConfig.Binds}},"mounts":{{json .Mounts}},"cap_drop":{{json .HostConfig.CapDrop}},"security_opt":{{json .HostConfig.SecurityOpt}},"pids_limit":{{json .HostConfig.PidsLimit}},"memory":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}},"read_only":{{json .HostConfig.ReadonlyRootfs}},"exit":{{json .State.ExitCode}},"oom_killed":{{json .State.OOMKilled}}}' "$1"
}
if [ "$mode" = all ] || [ "$mode" = prepare ]; then
    invalidate_dist
    docker build -f Dockerfile.prepare -t "$prepared" .
fi
if [ "$mode" = all ] || [ "$mode" = test ]; then
    invalidate_dist
    gate_context=$(mktemp -d /tmp/settlement-public-check.XXXXXX)
    gate_token=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
    sdk="settlement-match-sdk:$gate_token"
    runtime="settlement-match-runtime:$gate_token"
    docker build --network none --build-arg "PREPARED_IMAGE=$prepared" -f Dockerfile -t "$sdk" .
    sdk_container=$(docker create --network none --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g --cpus 2 --tmpfs /tmp:rw,exec,nosuid,nodev,size=512m "$sdk")
    docker start -a "$sdk_container"
    test "$(docker inspect -f '{{.State.ExitCode}}' "$sdk_container")" = 0
    mkdir -p dist/evidence
    docker cp "$sdk_container":/work/distributions/. dist/
    docker cp "$sdk_container":/work/evidence/. dist/evidence/
    inspect_owned "$sdk_container" > dist/sdk-container.json
    docker cp "$sdk_container":/opt/qualification/source-inventory.json "$gate_context/source-inventory.json"
    cp -R dist "$gate_context/distributions"
    cp Dockerfile.runtime "$gate_context/Dockerfile"
    cp scripts/consumer.py scripts/package_gate.py scripts/quality.py "$gate_context/"
    cp tests/data/hand-literal-graphs.compact.json fixtures/unique-input.json fixtures/unique-analysis.json "$gate_context/"
    python3 - "$gate_context" <<'PY'
import hashlib,json,sys
from pathlib import Path
context=Path(sys.argv[1]);source=Path('.')
proof=json.loads(Path('dist/evidence/package-proof.json').read_text())
(context/'module-hashes.json').write_text(json.dumps(proof['module_hashes'],indent=2)+'\n')
notices={p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('THIRD_PARTY').rglob('*')) if p.is_file()}
notices['LICENSE']=hashlib.sha256(Path('LICENSE').read_bytes()).hexdigest()
(context/'license-hashes.json').write_text(json.dumps(notices,indent=2)+'\n')
PY
    docker build --network none --build-arg "PREPARED_IMAGE=$prepared" -f "$gate_context/Dockerfile" -t "$runtime" "$gate_context"
    runtime_container=$(docker create --network none --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g --cpus 2 --read-only --tmpfs /tmp:rw,nosuid,nodev,size=32m "$runtime")
    docker start -a "$runtime_container"
    test "$(docker inspect -f '{{.State.ExitCode}}' "$runtime_container")" = 0
    inspect_owned "$runtime_container" > dist/runtime-container.json
    docker image inspect -f '{{.Id}}' "$sdk" > dist/sdk-image-id.txt
    docker image inspect -f '{{.Id}}' "$runtime" > dist/runtime-image-id.txt
fi
if [ "$mode" = all ] || [ "$mode" = demo ]; then
    runtime_id=$(cat dist/runtime-image-id.txt)
    python3 - "$runtime_id" <<'PY'
import re,sys
if not re.fullmatch('sha256:[0-9a-f]{64}',sys.argv[1]):raise SystemExit('invalid runtime image record')
PY
    docker run --rm --network none --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g --cpus 2 --read-only --tmpfs /tmp:rw,nosuid,nodev,size=32m "$runtime_id" /opt/settlement-runtime/bin/python -I -B -O -m settlement_match_workbench demo --assert
fi
