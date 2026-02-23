#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

USER_NAME="${SUDO_USER:-jinny}"
USER_HOME="$(getent passwd "${USER_NAME}" | cut -d: -f6)"
if [[ -z "${USER_HOME}" ]]; then
  echo "Cannot resolve home for user: ${USER_NAME}" >&2
  exit 1
fi

echo "[1/6] Installing OpenSSH server..."
apt-get update
apt-get install -y openssh-server curl

echo "[2/6] Enabling SSH service..."
systemctl enable --now ssh

echo "[3/6] Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh

echo "[4/6] Enabling tailscaled service..."
systemctl enable --now tailscaled

echo "[5/6] Applying safe SSH defaults..."
SSHD_CFG="/etc/ssh/sshd_config"
cp -a "${SSHD_CFG}" "${SSHD_CFG}.bak.$(date +%Y%m%d%H%M%S)"

ensure_sshd_line() {
  local key="$1"
  local value="$2"
  if grep -Eq "^[#[:space:]]*${key}[[:space:]]+" "${SSHD_CFG}"; then
    sed -i -E "s|^[#[:space:]]*${key}[[:space:]]+.*|${key} ${value}|g" "${SSHD_CFG}"
  else
    printf "\n%s %s\n" "${key}" "${value}" >> "${SSHD_CFG}"
  fi
}

ensure_sshd_line "PermitRootLogin" "no"
ensure_sshd_line "PubkeyAuthentication" "yes"
ensure_sshd_line "PasswordAuthentication" "yes"

sshd -t
systemctl restart ssh

echo "[6/6] Starting Tailscale login..."
tailscale up --ssh

TS_IP="$(tailscale ip -4 | head -n1 || true)"
echo
echo "Done."
echo "User: ${USER_NAME}"
echo "Tailscale IPv4: ${TS_IP:-not assigned yet}"
echo "SSH (Windows/Galaxy): ssh ${USER_NAME}@${TS_IP:-<tailscale-ip>}"
echo "Tip: run 'tailscale status' to verify other devices are connected."
