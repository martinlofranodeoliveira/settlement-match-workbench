# Settlement Match Workbench

A Python package and local CLI for explaining one-to-one assignments between
synthetic settlement lots and declared credit records. It first maximizes the
number of pairs, then minimizes the explicit reference/date preference cost.
It identifies edges present in every optimum, some optima, or no optimum, and
whether each record can remain unmatched. A representative is illustrative.

[Português](docs/README.pt-BR.md) · [CLI/I/O contract](docs/CLI-IO.md) ·
[Provenance](ORIGIN.md) · [Third-party notices](THIRD_PARTY.md)

The financial model admits exact integer minor units, an explicit currency
catalogue, inclusive date windows, and opaque case-sensitive references. Lots
use `net = gross - fees - refunds`; zero-net lots remain visible as
`NO_CREDIT_DUE`. Every lot×credit pair retains all applicable rejection reasons.
Money in JSON is a canonical decimal string, including 17-digit aggregates;
the report never combines different currencies into one money total.

`FORCED` means necessary across all optimal assignments for these inputs and
this policy. Credits are caller declarations, not bank observations. The model
does not cover FX, split payouts, disputes, reserves or provider integration.
The input digest identifies normalized input and does not authenticate it.

## Run the qualified package pipeline

Host prerequisites are Docker and Python3. The pinned runtime is CPython
3.13.18 on Debian12, with setuptools84.2.1/wheel0.48.0/packaging26.3 used only
for building. The package has no third-party runtime dependencies.

```sh
sh scripts/check.sh prepare
sh scripts/check.sh test
sh scripts/check.sh demo
```

Preparation downloads the three official wheels by exact URL and SHA256 and
uses a pinned official CPython image. Tests then run offline in containers with
UID1000, dropped capabilities, no host binds, 1GiB memory and2CPUs. The SDK gate
builds a genuine SDist and wheel, rebuilds from the SDist, verifies source and
license bytes, and runs the installed tests. A separate read-only runtime
installs only the rebuilt wheel and runs an independent consumer and real CLI.
It contains no checkout, build backend or compiler. Output artifacts and
container evidence are retained in generated `dist/`; old output is removed
before preparation/test and symlinked output is refused. `sh scripts/check.sh`
runs all three steps. Hosted CI is a separate observation.

After installing the rebuilt wheel in CPython3.13.18:

```sh
settlement-match-workbench demo --assert
settlement-match-workbench analyze --input fixtures/unique-input.json
settlement-match-workbench analyze --input - --max-work 50000000 --max-output-bytes 524288 < fixtures/unique-input.json
```

The demo runs the actual SDK and compares its entire Analysis with an independent
synthetic literal. Its checks remain enabled under `python -O`. SDK bytes, with
their final LF, are written unchanged. Logical failure produces no stdout
report. A physical output failure can occur after a partial OS write.

## Python API and finite scope

```python
from settlement_match_workbench.financial import analyze_json

with open("fixtures/unique-input.json", "rb") as source:
    result = analyze_json(source.read())
print(result.status.value, result.code, result.work_used)
# result.json_bytes is the complete canonical report, including LF.
```

`analyze(Scenario(...), Limits(...))` is the typed SDK boundary. DTO money must
be exact `int`, excluding bool; wire money must be strings. Raw JSON is limited
to524288bytes, with closed objects, duplicate-key refusal and no numeric
coercion. Inputs allow1..8currency codes,0..16lots,0..16credits and at most128
candidates. Date years are2000..2099; each policy window is0..31days. Generic
graph `solve(Problem(...))` has the same16×16/128edge cap and integer costs.

One global logical work budget covers construction, solver probes and reports:
default50million, hard100million. Insufficient work returns
`UNKNOWN_BUDGET/WORK_LIMIT` with no Analysis. Complete report bytes are capped
at524288including LF. Work counts describe this implementation's logical meter,
not wall-clock time or CPU instructions. There is no general runtime guarantee.

CLI exits:0complete,2invalid/usage,3I/O,4unknown budget,5internal error. Failure
frames go to stderr; help/version are human text. Local paths may be readable
regular files or symlinks to them. Stdin requires complete EOF. No network,
credentials, provider calls or output-file writer is part of this API/CLI.
