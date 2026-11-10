The files under `THIRD_PARTY/` retain actual license and notice bytes from the
qualified artifacts. They are records of provenance, not additional runtime
dependencies of this package.

`BUILD_WHEELS/` contains 21 license/notice members from the SHA256-locked
setuptools 84.2.1, wheel 0.48.0, and packaging 26.3 wheels, including notices
shipped for vendored code. `build-wheel-notices.json` identifies every member.

`SDK_NATIVE/` contains 218 license/notice files read from the actual pinned
CPython 3.13.18 Debian 12 image and its installed build virtual environment.
This includes the operating system, CPython, pip, and the build tools.
`sdk-native-notices.json` records the source paths and byte hashes. The
runtime uses the same qualified CPython image; build tools are kept in a
separate virtual environment and are not runtime requirements.

The package itself uses the Python standard library. Its license is `LICENSE`.
