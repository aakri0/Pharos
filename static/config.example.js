// Copy to static/config.js (or generate via Vercel env vars at build) for
// the production Vercel → HuggingFace Space deployment. Both values are
// optional; if either is omitted, app.js falls back to same-origin /api/*
// calls without an X-API-Key header.

window.PHAROS_API_BASE = "https://<YOUR-HF-USERNAME>-<YOUR-SPACE-NAME>.hf.space";
window.PHAROS_API_KEY  = "<paste the same value you set as PHAROS_API_KEY on the HF Space>";
