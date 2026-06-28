#!/usr/bin/env sh
# Vercel build script — generates static/config.js from environment
# variables so the deployed frontend can talk to the HF Space backend
# without committing the API key to the repo.
#
# Set both vars under Vercel project settings → Environment Variables
# (Production scope is fine for both):
#   PHAROS_API_BASE   e.g. https://aakri0-pharos.hf.space
#   PHAROS_API_KEY    the random string also set as a Space secret
#
# If either var is unset, the frontend falls back to same-origin /api
# calls (which won't work on Vercel because there's no backend there).

set -eu

if [ -z "${PHAROS_API_BASE:-}" ] || [ -z "${PHAROS_API_KEY:-}" ]; then
  echo "WARN: PHAROS_API_BASE or PHAROS_API_KEY is not set — config.js" >&2
  echo "      will be empty and the deployed frontend will not be able" >&2
  echo "      to reach the backend. Set both in Vercel project settings." >&2
  : > static/config.js
  exit 0
fi

cat > static/config.js <<EOF
// Generated at Vercel build time from project environment variables.
// Do not commit — static/config.js is .gitignored.
window.PHAROS_API_BASE = "${PHAROS_API_BASE}";
window.PHAROS_API_KEY  = "${PHAROS_API_KEY}";
EOF

echo "Generated static/config.js with PHAROS_API_BASE=${PHAROS_API_BASE}"
