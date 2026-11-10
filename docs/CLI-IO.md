# Local CLI contract

Commands: `analyze --input FILE|- [--max-work N] [--max-output-bytes N]`,
`demo [--assert]` with the same numeric options, standalone `--help`,
`--version`, and subcommand `--help`. Unknown, duplicated, abbreviated or
coerced options are CLI_USAGE. Canonical ASCII integer options have no signs
or leading zeros. Work defaults to50000000, maximum100000000; output defaults
to524288, maximum524288. Zero is admitted for both.

Input paths are explicit local caller choices. Readable regular files,
including another owner's file and symlinks to regular files, are accepted.
Read-only NONBLOCK/CLOEXEC opening and fstat reject FIFOs, sockets, devices and
directories before reading. The same FD is read and checked before/after for
device/inode/type/size/mtime/ctime changes. No UID, link-count or NOFOLLOW
restriction applies. This detects some modifications, not an atomic snapshot.

File/stdin reads continue through positive short reads to explicit empty-byte
EOF. None, a read error or detectable file change is INPUT_IO. At most524289
bytes are retained; the sentinel byte delegates over-cap input to SDK SIZE.
No retained prefix is analyzed on I/O failure. Blocking stdin has no promised
wall-clock deadline. Demo/help/version do not read stdin.

The genuine SDK produces the complete canonical frame before stdout is touched.
COMPLETE stdout is exactly `ReportResult.json_bytes`, including LF. The chosen
output cap counts all those bytes. Overflow instead emits
UNKNOWN_BUDGET/CLI_OUTPUT_BYTES on stderr, with actual observed work and
analysis=null. Outputcap0 still performs input and SDK admission first. Failed
SDK outcomes are copied to stderr without reserialization, preserving codes.

| Outcome | Exit |
|---|---:|
| COMPLETE |0|
| INVALID_INPUT or CLI_USAGE |2|
| INPUT_IO or OUTPUT_IO |3|
| UNKNOWN_BUDGET, including CLI_OUTPUT_BYTES |4|
| INTERNAL_ERROR or CLI_INTERNAL |5|

Adapter diagnostics use the same exact closed frame keys, canonical ASCII JSON,
LF and analysis=null. They do not echo arbitrary exception/input/path text.
CLI-only codes do not extend the pure SDK's code set. Stderr is best effort;
secondary stderr failure preserves primary2/4/5. Help/version stdout failure
is3. Only a failed FD1/FD2 is quieted before interpreter shutdown to prevent
finalizer exit120. There is no claim of physical stdout atomicity or rollback:
an OS write may have sent a prefix before failing.

The synthetic demo calls the real SDK. Its optional full-Analysis checks use
explicit conditions active under optimization; the expected literal is not
emitted as an execution result and no work count is hardcoded.
