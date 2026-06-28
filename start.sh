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
import os, shutil
from huggingface_hub import hf_hub_download

path = hf_hub_download(
    repo_id=os.environ["PHAROS_DB_REPO"],
    filename=os.environ["PHAROS_DB_FILENAME"],
    repo_type="dataset",
    token=os.environ["HF_TOKEN"],
)
target = os.environ["PHAROS_DB"]
# hf_hub_download returns a path inside the HF cache. Move (not copy) so we
# don't keep two copies in the container's ephemeral disk.
shutil.move(path, target)
print(f"Downloaded {target} ({os.path.getsize(target) / (1024*1024):,.1f} MB)")
PY
fi

echo "Starting Pharos backend on ${PHAROS_HOST:-0.0.0.0}:${PORT:-7860}"
exec python3 app.py
