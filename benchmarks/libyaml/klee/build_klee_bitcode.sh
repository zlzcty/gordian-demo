#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/klee/build"
INCLUDE_DIR="${BUILD_DIR}/include"
LIB_DIR="${BUILD_DIR}/libyaml"
BIN_DIR="${BUILD_DIR}/bin"

CLANG_BIN="${CLANG_BIN:-clang}"
LLVM_LINK_BIN="${LLVM_LINK_BIN:-llvm-link}"
CFLAGS=(
  -I"${ROOT_DIR}/include"
  -I"${INCLUDE_DIR}"
  -I/usr/include
  -DHAVE_CONFIG_H=1
  -DYAML_DECLARE_STATIC=1
  -g
  -O0
  -emit-llvm
  -c
)

mkdir -p "${INCLUDE_DIR}" "${LIB_DIR}" "${BIN_DIR}"

cat > "${INCLUDE_DIR}/config.h" <<'EOF'
#define YAML_VERSION_MAJOR 0
#define YAML_VERSION_MINOR 2
#define YAML_VERSION_PATCH 5
#define YAML_VERSION_STRING "0.2.5"
EOF

compile_bc() {
  local src_path="$1"
  local out_path="$2"
  local extra_flags=()

  if "${CLANG_BIN}" -x c - -c -o /dev/null -Xclang -disable-O0-optnone </dev/null >/dev/null 2>&1; then
    extra_flags+=(-Xclang -disable-O0-optnone)
  fi

  "${CLANG_BIN}" "${CFLAGS[@]}" "${extra_flags[@]}" "${src_path}" -o "${out_path}"
}

compile_set() {
  local prefix="$1"
  shift
  local src_path
  local bc_paths=()

  for src_path in "$@"; do
    local base_name
    local out_path
    base_name="$(basename "${src_path}" .c)"
    out_path="${LIB_DIR}/${prefix}_${base_name}.bc"
    compile_bc "${src_path}" "${out_path}"
    bc_paths+=("${out_path}")
  done

  printf '%s\n' "${bc_paths[@]}"
}

PARSER_SRCS=(
  "${ROOT_DIR}/src/api.c"
  "${ROOT_DIR}/src/reader.c"
  "${ROOT_DIR}/src/scanner.c"
  "${ROOT_DIR}/src/parser.c"
)

SCANNER_SRCS=(
  "${ROOT_DIR}/src/api.c"
  "${ROOT_DIR}/src/reader.c"
  "${ROOT_DIR}/src/scanner.c"
)

readarray -t PARSER_BCS < <(compile_set parser "${PARSER_SRCS[@]}")
readarray -t SCANNER_BCS < <(compile_set scanner "${SCANNER_SRCS[@]}")
compile_bc "${ROOT_DIR}/klee/libyaml_klee_compat.c" "${LIB_DIR}/klee_compat.bc"

for src_path in "${PARSER_SRCS[@]}" "${SCANNER_SRCS[@]}"; do
  base_name="$(basename "${src_path}" .c)"
  :
done

compile_bc "${ROOT_DIR}/klee/libyaml_parser_harness.c" "${BIN_DIR}/libyaml_parser_harness.bc"
compile_bc "${ROOT_DIR}/klee/libyaml_scanner_harness.c" "${BIN_DIR}/libyaml_scanner_harness.bc"

"${LLVM_LINK_BIN}" "${PARSER_BCS[@]}" "${LIB_DIR}/klee_compat.bc" "${BIN_DIR}/libyaml_parser_harness.bc" -o "${BIN_DIR}/libyaml_parser.bc"
"${LLVM_LINK_BIN}" "${SCANNER_BCS[@]}" "${LIB_DIR}/klee_compat.bc" "${BIN_DIR}/libyaml_scanner_harness.bc" -o "${BIN_DIR}/libyaml_scanner.bc"

printf 'Wrote %s\n' "${BIN_DIR}/libyaml_parser.bc"
printf 'Wrote %s\n' "${BIN_DIR}/libyaml_scanner.bc"
