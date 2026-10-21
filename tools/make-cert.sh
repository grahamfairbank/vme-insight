#!/usr/bin/env bash
# Make a certificate for vme-insight's https front end that you can inspect before trusting.
# Every openssl command is printed before it runs; --dry-run prints them without running.
#
#   tools/make-cert.sh host NAME [NAME|IP ...]          (recommended)
#       A self-signed certificate for these names only (CA:FALSE). Browsers that trust it
#       trust exactly this certificate; it cannot be used to sign anything else.
#
#   tools/make-cert.sh ca --permit DOMAIN|CIDR [...] NAME [NAME|IP ...]
#       A private CA limited by name constraints to the permitted domains/networks, plus a
#       server certificate signed by it. Trust the CA once; reissue server certificates
#       later without touching browsers. Keep the CA key OFF the vme-insight host.
#
# Options:
#   --out DIR       where the server certificate and key go (default: https/certs)
#   --ca-dir DIR    where the CA lives (default: ~/vme-insight-ca), ca mode only
#   --days N        server certificate validity (default 397; Apple rejects more than 825)
#   --ca-days N     CA validity (default 1826), ca mode only
#   --dry-run       print the commands only
#
# Examples:
#   tools/make-cert.sh host vme-insight.corp.example 10.0.0.25
#   tools/make-cert.sh ca --permit corp.example --permit 10.0.0.0/24 vme-insight.corp.example 10.0.0.25
#
# Then set in .env:  HTTPS_TLS="/certs/vme-insight.crt /certs/vme-insight.key"
# and run:           docker compose --profile https up -d https
# See docs/VME-PLUGIN.md, "Make browsers trust the certificate".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/https/certs"
CA_DIR="$HOME/vme-insight-ca"
DAYS=397
CA_DAYS=1826
DRY=0
MODE="${1:-}"
shift || true
PERMIT=()
NAMES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --ca-dir) CA_DIR="$2"; shift 2 ;;
    --days) DAYS="$2"; shift 2 ;;
    --ca-days) CA_DAYS="$2"; shift 2 ;;
    --permit) PERMIT+=("$2"); shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) NAMES+=("$1"); shift ;;
  esac
done
[[ "$MODE" == host || "$MODE" == ca ]] || { sed -n '2,29p' "$0"; exit 2; }
[[ ${#NAMES[@]} -gt 0 ]] || { echo "give at least one hostname or IP the browser will use" >&2; exit 2; }
[[ "$MODE" == host || ${#PERMIT[@]} -gt 0 ]] || { echo "ca mode needs at least one --permit DOMAIN or CIDR" >&2; exit 2; }

is_ip() { [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; }
SAN=""
for n in "${NAMES[@]}"; do
  if is_ip "$n"; then SAN+="IP:$n,"; else SAN+="DNS:$n,"; fi
done
SAN="${SAN%,}"
CN="${NAMES[0]}"

run() {  # print, then run unless --dry-run
  printf '\n$'; printf ' %q' "$@"; printf '\n'
  [[ $DRY -eq 1 ]] || "$@"
}
fingerprint() {
  openssl x509 -in "$1" -noout -fingerprint -sha256 | sed 's/^.*=//'
}

CRT="$OUT/vme-insight.crt"
KEY="$OUT/vme-insight.key"
[[ $DRY -eq 1 ]] || mkdir -p "$OUT"
LEAF_EXT=(-addext "subjectAltName=$SAN"
          -addext "basicConstraints=critical,CA:FALSE"
          -addext "keyUsage=critical,digitalSignature"
          -addext "extendedKeyUsage=serverAuth")

if [[ "$MODE" == host ]]; then
  echo "# Self-signed server certificate for: ${NAMES[*]}"
  run openssl req -x509 -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256 \
      -days "$DAYS" -subj "/CN=$CN/O=vme-insight" "${LEAF_EXT[@]}" -keyout "$KEY" -out "$CRT"
  run chmod 600 "$KEY"
  TRUST="$CRT"
else
  # name constraints: DNS domains and IP networks the CA may issue for, nothing else
  NC="critical"
  for p in "${PERMIT[@]}"; do
    if [[ "$p" =~ ^([0-9.]+)/([0-9]+)$ ]]; then
      bits="${BASH_REMATCH[2]}"; mask=""
      for i in 0 1 2 3; do
        b=$(( bits >= 8 ? 8 : (bits > 0 ? bits : 0) )); bits=$(( bits - b ))
        mask+="$(( 256 - (1 << (8 - b)) )).";
      done
      NC+=",permitted;IP:${BASH_REMATCH[1]}/${mask%.}"
    else
      NC+=",permitted;DNS:$p"
    fi
  done
  CA_CRT="$CA_DIR/vme-insight-ca.crt"
  CA_KEY="$CA_DIR/vme-insight-ca.key"
  if [[ -f "$CA_KEY" ]]; then
    echo "# Reusing the CA in $CA_DIR (delete it to start over)"
  else
    echo "# Name-constrained CA in $CA_DIR (permitted: ${PERMIT[*]})"
    [[ $DRY -eq 1 ]] || { mkdir -p "$CA_DIR"; chmod 700 "$CA_DIR"; }
    run openssl req -x509 -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256 \
        -days "$CA_DAYS" -subj "/CN=vme-insight private CA/O=vme-insight" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "nameConstraints=$NC" -keyout "$CA_KEY" -out "$CA_CRT"
    run chmod 600 "$CA_KEY"
  fi
  echo "# Server certificate for: ${NAMES[*]}, signed by that CA"
  run openssl req -x509 -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256 \
      -days "$DAYS" -subj "/CN=$CN/O=vme-insight" "${LEAF_EXT[@]}" \
      -CA "$CA_CRT" -CAkey "$CA_KEY" -keyout "$KEY" -out "$CRT"
  run chmod 600 "$KEY"
  run openssl verify -CAfile "$CA_CRT" "$CRT"
  TRUST="$CA_CRT"
fi

[[ $DRY -eq 1 ]] && { echo; echo "# dry run: nothing written"; exit 0; }
echo
echo "== What to trust on each browser machine: $TRUST"
openssl x509 -in "$TRUST" -noout -subject -issuer -dates -ext basicConstraints,nameConstraints,subjectAltName 2>/dev/null | sed 's/^/   /'
echo "   SHA-256 fingerprint: $(fingerprint "$TRUST")"
echo
echo "== Server files (keep the key private; https/certs is git-ignored)"
echo "   $CRT"
echo "   $KEY"
[[ "$MODE" == ca ]] && echo "   CA key: $CA_KEY  <- move this off the vme-insight host"
echo
echo "== Next"
echo "   1. In .env:  HTTPS_TLS=\"/certs/vme-insight.crt /certs/vme-insight.key\""
echo "   2. docker compose --profile https up -d https"
echo "   3. On each browser machine, check the fingerprint above, then import $(basename "$TRUST")"
echo "      (docs/VME-PLUGIN.md, \"Make browsers trust the certificate\")."
