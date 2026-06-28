#!/usr/bin/env bash
# Boot script for the Pharos backend container.
#
# Required env (set as HuggingFace Space "Secrets"):
#   HF_TOKEN              HF user/access token with read access to the
#                         private Dataset that holds the DrugBank file
#   PHAROS_DB_REPO        Dataset id, e.g. "yourname/pharos-drugbank"
#   PHAROS_DB_FILENAME    File path inside the dataset, e.g. "drugbank_full.db"
#
# Optional (but recommended in production):
#   PHAROS_API_KEY        Shared secret that /api/* will require
#   PHAROS_ALLOWED_ORIGIN Vercel URL allowed to call this backend
#                         (e.g. "https://pharos.vercel.app")

set -euo pipefail

: "${PHAROS_DB:=/app/data/drugbank_full.db}"
: "${PHAROS_DB_FILENAME:=drugbank_full.db}"

mkdir -p "$(dirname "$PHAROS_DB")"

if [[ ! -f "$PHAROS_DB" ]]; then
  if [[ -z "${HF_TOKEN:-}" || -z "${PHAROS_DB_REPO:-}" ]]; then
    echo "ERROR: $PHAROS_DB is missing and HF_TOKEN / PHAROS_DB_REPO are not set." >&2
    echo "       Set them as Space Secrets so the DB can be downloaded." >&2
    exit 1
  fi

  echo "Fetching $PHAROS_DB_FILENAME from private dataset $PHAROS_DB_REPO ..."
  python3 - <<'PY'
import os, sys
from huggingface_hub import hf_hub_download

target = os.environ["PHAROS_DB"]
target_dir = os.path.dirname(target)
filename = os.environ["PHAROS_DB_FILENAME"]

# Download directly to the target directory instead of pulling into the
# default HF cache and then shutil.move'ing. local_dir writes the actual
# blob file in place (no symlink, no Xet stub) which avoids the silent
# "moved an empty cache stub" failure the older shuffle was prone to on
# Xet-backed datasets.
path = hf_hub_download(
    repo_id=os.environ["PHAROS_DB_REPO"],
    filename=filename,
    repo_type="dataset",
    token=os.environ["HF_TOKEN"],
    local_dir=target_dir,
)

if not os.path.exists(target) or os.path.getsize(target) == 0:
    sys.exit(
        f"ERROR: hf_hub_download returned {path!r} but {target} is missing "
        f"or empty. Likely cause: HF Xet support not installed in this "
        f"image — confirm Dockerfile installs huggingface_hub[hf_xet]>=0.27."
    )

size_mb = os.path.getsize(target) / (1024 * 1024)
print(f"Downloaded {target} ({size_mb:,.1f} MB)")
PY
fi

echo "Starting Pharos backend on ${PHAROS_HOST:-0.0.0.0}:${PORT:-7860}"
exec python3 app.py
