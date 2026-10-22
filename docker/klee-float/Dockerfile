# KLEE-Float backend for Gordian.
#
# Reproduces the image used in the paper: upstream srg-imperial/klee-float at
# commit aa907655 (the same source the authors' `klee_float_image` was built
# from, verified file-by-file), built on top of the public
# comsys/klee-dev-fpbench-prebuilt image exactly as klee-float's own
# scripts/patch_aachen.Dockerfile does.  The only change relative to upstream is
# the pacman-static mirror, which has moved since 2017.
#
# Build:  docker build -t gordian-klee-float -f docker/klee-float/Dockerfile docker/klee-float
#
# The resulting image has `klee` (KLEE 1.3-based, LLVM 3.4, Z3 solver with
# floating-point support), `clang`, `gcov`, and `python3` on PATH, with the
# non-root user `user` whose home is /home/user.
FROM comsys/klee-dev-fpbench-prebuilt:latest

ARG host_user_id=1000
ARG container_username=user
ARG klee_git_hash=aa907655cd9ec030036424acf88d9cb41a93a93b

USER root
RUN rm -rf /home/${container_username}/klee && mkdir /home/${container_username}/klee && \
    usermod --uid ${host_user_id} ${container_username} && \
    chmod 0755 /home/${container_username}/

# Install tcmalloc (gperftools) so KLEE can enforce a memory limit.  The base
# image is Arch-based with a stale pacman; use pacman-static from a live mirror.
RUN wget -O pacman-static https://pkgbuild.com/~morganamilo/pacman-static/x86_64/bin/pacman-static \
 && chmod +x pacman-static \
 && ./pacman-static -Syy && ./pacman-static -S --noconfirm gperftools git

USER ${container_username}
WORKDIR /home/${container_username}/

# Fetch the exact klee-float revision.
RUN git clone https://github.com/srg-imperial/klee-float klee && \
    cd klee && git checkout ${klee_git_hash} && \
    cp scripts/container.Makefile /home/${container_username}/makefile

# Build KLEE with the Aachen makefile (uclibc + POSIX runtime + Z3).
RUN make klee
USER root
RUN cd /home/${container_username}/klee/build && make install
USER ${container_username}

LABEL klee_git_hash=${klee_git_hash}
ENV LLVM_COMPILER=clang
ENV KLEE_NATIVE_RUNTIME_INCLUDE_DIR=/home/user/klee/include/
ENV KLEE_NATIVE_RUNTIME_LIB_DIR=/home/user/klee/build/lib/
CMD [ "/bin/sh", "-c", "/usr/bin/bash -l" ]
