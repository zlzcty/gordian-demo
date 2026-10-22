#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./klee/calc_coverage.sh <src-file> <ktest-dir> [output-dir]

Examples:
  ./klee/calc_coverage.sh src/parser.c klee/out/libyaml_parser_baseline
  ./klee/calc_coverage.sh src/scanner.c klee/out/libyaml_scanner_baseline /tmp/libyaml_cov

Notes:
  - Run this inside the Docker container where KLEE generated the .ktest files.
  - Supported src files: src/parser.c, src/scanner.c
  - Set SKIP_REPLAY=1 to reuse existing .profraw files in the output dir.
  - Set BATCH_SIZE=<n> to control llvm-profdata merge chunk size (default: 2000).
EOF
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ARG="$1"
KTEST_DIR="$2"
OUT_DIR="${3:-}"
SKIP_REPLAY="${SKIP_REPLAY:-0}"
BATCH_SIZE="${BATCH_SIZE:-2000}"

SRC_PATH="$(realpath -m "${SRC_ARG}")"
KTEST_PATH="$(realpath -m "${KTEST_DIR}")"

if [[ ! -f "${SRC_PATH}" ]]; then
  echo "error: source file not found: ${SRC_ARG}" >&2
  exit 1
fi

if [[ ! -d "${KTEST_PATH}" ]]; then
  echo "error: ktest directory not found: ${KTEST_DIR}" >&2
  exit 1
fi

case "$(basename "${SRC_PATH}")" in
  parser.c)
    HARNESS="${ROOT_DIR}/klee/libyaml_parser_harness.c"
    TARGET_NAME="parser"
    TARGET_SRCS=(
      "${ROOT_DIR}/src/api.c"
      "${ROOT_DIR}/src/reader.c"
      "${ROOT_DIR}/src/scanner.c"
      "${ROOT_DIR}/src/parser.c"
    )
    ;;
  scanner.c)
    HARNESS="${ROOT_DIR}/klee/libyaml_scanner_harness.c"
    TARGET_NAME="scanner"
    TARGET_SRCS=(
      "${ROOT_DIR}/src/api.c"
      "${ROOT_DIR}/src/reader.c"
      "${ROOT_DIR}/src/scanner.c"
    )
    ;;
  *)
    echo "error: unsupported source file: ${SRC_ARG}" >&2
    echo "supported files: src/parser.c, src/scanner.c" >&2
    exit 1
    ;;
esac

if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="/tmp/libyaml_${TARGET_NAME}_coverage"
fi

OUT_DIR="$(realpath -m "${OUT_DIR}")"
BUILD_INCLUDE_DIR="${ROOT_DIR}/klee/build/include"
REPLAY_EXE="${OUT_DIR}/ghost_coverage"
PROFDATA="${OUT_DIR}/ghost.profdata"
SHOW_TXT="${OUT_DIR}/${TARGET_NAME}_cov_show.txt"
REPORT_TXT="${OUT_DIR}/${TARGET_NAME}_cov_report.txt"
TMP_MERGE_DIR="${OUT_DIR}/merge_batches"

if [[ "${SKIP_REPLAY}" != "1" ]]; then
  rm -rf "${OUT_DIR}"
fi
mkdir -p "${OUT_DIR}"

if [[ ! -f "${BUILD_INCLUDE_DIR}/config.h" ]]; then
  "${ROOT_DIR}/klee/build_klee_bitcode.sh" >/dev/null
fi

clang -O0 -g -fprofile-instr-generate -fcoverage-mapping -fno-inline -fno-builtin \
  -DHAVE_CONFIG_H=1 -DYAML_DECLARE_STATIC=1 \
  -I/tmp/klee_build130stp_z3/include \
  -I"${ROOT_DIR}/include" \
  -I"${BUILD_INCLUDE_DIR}" \
  "${HARNESS}" \
  "${ROOT_DIR}/klee/libyaml_klee_compat.c" \
  "${TARGET_SRCS[@]}" \
  -L/tmp/klee_build130stp_z3/lib \
  -lkleeRuntest -lpthread -lm \
  -o "${REPLAY_EXE}"

shopt -s nullglob
KTEST_FILES=( "${KTEST_PATH}"/*.ktest )
shopt -u nullglob

if [[ ${#KTEST_FILES[@]} -eq 0 ]]; then
  echo "error: no .ktest files found in ${KTEST_DIR}" >&2
  exit 1
fi

if [[ "${SKIP_REPLAY}" != "1" ]]; then
  for ktest in "${KTEST_FILES[@]}"; do
    base="$(basename "${ktest}")"
    LLVM_PROFILE_FILE="${OUT_DIR}/${base}.profraw" \
    KTEST_FILE="${ktest}" \
    LD_PRELOAD=/tmp/libflushcov.so \
    "${REPLAY_EXE}" >/dev/null 2>&1 || true
  done
fi

merge_batch_lists() {
  local source_glob_dir="$1"
  local pattern="$2"
  local output_file="$3"
  local work_dir="$4"

  rm -rf "${work_dir}"
  mkdir -p "${work_dir}/lists" "${work_dir}/parts"

  find "${source_glob_dir}" -maxdepth 1 -type f -name "${pattern}" | sort > "${work_dir}/all_files.txt"
  if [[ ! -s "${work_dir}/all_files.txt" ]]; then
    echo "error: no files found for merge pattern ${pattern} in ${source_glob_dir}" >&2
    exit 1
  fi

  split -l "${BATCH_SIZE}" -d -a 4 "${work_dir}/all_files.txt" "${work_dir}/lists/batch_"

  local idx=0
  for list_file in "${work_dir}"/lists/batch_*; do
    mapfile -t batch_files < "${list_file}"
    if [[ ${#batch_files[@]} -eq 0 ]]; then
      continue
    fi
    local part_file="${work_dir}/parts/part_$(printf '%04d' "${idx}").profdata"
    llvm-profdata merge -sparse "${batch_files[@]}" -o "${part_file}"
    idx=$((idx + 1))
  done

  shopt -s nullglob
  local part_files=( "${work_dir}"/parts/*.profdata )
  shopt -u nullglob
  if [[ ${#part_files[@]} -eq 0 ]]; then
    echo "error: no intermediate profdata files were created" >&2
    exit 1
  fi

  llvm-profdata merge -sparse "${part_files[@]}" -o "${output_file}"
}

merge_batch_lists "${OUT_DIR}" "*.profraw" "${PROFDATA}" "${TMP_MERGE_DIR}"

llvm-cov report "${REPLAY_EXE}" \
  -instr-profile="${PROFDATA}" \
  "${SRC_PATH}" | tee "${REPORT_TXT}"

llvm-cov show "${REPLAY_EXE}" \
  -instr-profile="${PROFDATA}" \
  "${SRC_PATH}" > "${SHOW_TXT}"

printf '\nWrote report to %s\n' "${REPORT_TXT}"
printf 'Wrote line coverage to %s\n' "${SHOW_TXT}"
