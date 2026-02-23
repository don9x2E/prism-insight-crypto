#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "${repo_root}"

python_bin="${repo_root}/.venv/bin/python"
if [[ ! -x "${python_bin}" ]]; then
  echo "Python venv not found: ${python_bin}" >&2
  exit 1
fi

log_dir="${repo_root}/logs"
mkdir -p "${log_dir}"
log_file="${log_dir}/crypto_scheduler_$(date +%Y%m%d).log"
export TMPDIR="/data/Prism_BackUp/tmp"
mkdir -p "${TMPDIR}"

write_log() {
  local message="$1"
  local line
  line="[$(date '+%Y-%m-%d %H:%M:%S')] ${message}"
  echo "${line}" | tee -a "${log_file}" >/dev/null
}

run_python_and_log() {
  local step_name="$1"
  shift

  local out_file err_file
  out_file="$(mktemp "${log_dir}/tmp_${step_name}_XXXXXX.out.log")"
  err_file="$(mktemp "${log_dir}/tmp_${step_name}_XXXXXX.err.log")"

  set +e
  "${python_bin}" "$@" >"${out_file}" 2>"${err_file}"
  local exit_code=$?
  set -e

  while IFS= read -r line; do
    [[ -n "${line}" ]] && write_log "${line}"
  done <"${out_file}"
  while IFS= read -r line; do
    [[ -n "${line}" ]] && write_log "${line}"
  done <"${err_file}"

  rm -f "${out_file}" "${err_file}"

  if [[ ${exit_code} -ne 0 ]]; then
    write_log "${step_name} failed with exit code ${exit_code}"
    exit "${exit_code}"
  fi
}

CYCLE_HOURS=2
current_hour="$(date +%H)"
if (( 10#${current_hour} % CYCLE_HOURS != 0 )); then
  write_log "Skipping cycle: 2h cadence gate (hour=${current_hour})"
  exit 0
fi

# Disable proxy variables that can break market data calls.
export ALL_PROXY=""
export HTTP_PROXY=""
export HTTPS_PROXY=""
export GIT_HTTP_PROXY=""
export GIT_HTTPS_PROXY=""

write_log "Crypto hourly paper cycle started"

exclude_symbols="$("${python_bin}" - <<'PY'
import sqlite3
try:
    conn = sqlite3.connect("stock_tracking_db.sqlite")
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM crypto_holdings WHERE symbol IS NOT NULL")
    rows = [str(r[0]).strip().upper() for r in cur.fetchall() if r and r[0]]
    unique = sorted(set(x for x in rows if x))
    print(",".join(unique))
finally:
    try:
        conn.close()
    except Exception:
        pass
PY
)"

trigger_args=(
  -m crypto.crypto_trigger_batch
  --interval 2h
  --period 14d
  --max-positions 3
  --fallback-max-entries 3
  --output crypto_candidates.json
)
if [[ -n "${exclude_symbols}" ]]; then
  trigger_args+=(--exclude-symbols "${exclude_symbols}")
  write_log "Excluding held symbols in phase1: ${exclude_symbols}"
fi

run_python_and_log "crypto_trigger_batch" "${trigger_args[@]}"

run_python_and_log "crypto_tracking_agent" \
  -m crypto.crypto_tracking_agent \
  crypto_candidates.json \
  --db-path stock_tracking_db.sqlite \
  --language ko \
  --timeframe 2h \
  --execute-trades \
  --trade-mode paper \
  --quote-amount 100

run_python_and_log "generate_crypto_benchmark_json" \
  ./examples/generate_crypto_benchmark_json.py \
  --db-path stock_tracking_db.sqlite \
  --output-path ./examples/dashboard/public/crypto_benchmark_data.json \
  --initial-capital 1000

run_python_and_log "crypto_cycle_metrics" \
  ./scripts/crypto_cycle_metrics.py \
  --db-path stock_tracking_db.sqlite \
  --roundtrip-cost-pct 0.3

write_log "Crypto hourly paper cycle completed"
