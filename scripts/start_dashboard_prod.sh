#!/usr/bin/env bash
set -euo pipefail

repo_root="/home/jinny/prism-insight-crypto"
dashboard_dir="${repo_root}/examples/dashboard"
node_bin="/home/jinny/.local/node/node-v20.19.5-linux-x64/bin"
log_dir="${repo_root}/logs"
log_file="${log_dir}/dashboard_server.log"

mkdir -p "${log_dir}"
cd "${dashboard_dir}"

export PATH="${node_bin}:${PATH}"
export NODE_ENV=production
export TMPDIR="/data/Prism_BackUp/tmp"
mkdir -p "${TMPDIR}"

# Avoid duplicate server processes after repeated reboot hooks.
if pgrep -f "next start.*--port 3000" >/dev/null 2>&1; then
  exit 0
fi

nohup "${node_bin}/npm" run start -- --hostname 127.0.0.1 --port 3000 >>"${log_file}" 2>&1 &
