# Standard KLEE 3.0 backend for Gordian (Z3 + STP, LLVM 13, uclibc, POSIX runtime).
#
# This is the official klee/klee:3.0 image plus the few host tools Gordian's
# coverage replay needs inside the container (gcov is already present; we add
# python3 pip packages used by the in-container helper scripts).
#
# Build:  docker build -t gordian-klee -f docker/klee/Dockerfile docker/klee
FROM klee/klee:3.0

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip bc jq file rsync && \
    rm -rf /var/lib/apt/lists/*
USER klee
WORKDIR /home/klee
# `klee`, `clang` (LLVM 13), `gcov`, `llvm-cov`, `klee-replay`, `ktest-tool` are on PATH.
