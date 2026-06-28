# Deploying Pharos

Two pieces, deployed separately:

- **Frontend** (static HTML/CSS/JS in `static/`) → **Vercel**
- **Backend** (Python `http.server` + DrugBank SQLite) → **HuggingFace Space** (Docker SDK)
- **Database** (2.4 GB licensed DrugBank file) → **HuggingFace private Dataset** that the Space downloads at container start

All three live on free tiers, no credit card required.

> ⚠️ Cold-start note: the HF Space sleeps after 48 h of inactivity. The very
> first visitor after a sleep waits ~5–10 min while the container restarts
> and re-downloads the 2.4 GB DB from the private Dataset. Subsequent
> visitors are fast until the next sleep cycle. There is no free way to
> avoid this — persistent disk is a paid feature on every host we evaluated.

---

## 1. Upload the DB to a private HuggingFace Dataset

1. Create an account at <https://huggingface.co/join> (free, no CC).
2. <https://huggingface.co/new-dataset> → **set visibility to Private**, name it e.g. `pharos-drugbank`.
3. Upload `drugbank_full.db` via the **Files** tab → "Add file" → drag-and-drop.
   The web uploader handles 2.4 GB; if it stalls, install the CLI:
   ```bash
   pip install huggingface_hub
   huggingface-cli login                       # paste a write-token from /settings/tokens
   huggingface-cli upload <YOU>/pharos-drugbank drugbank_full.db drugbank_full.db --repo-type=dataset
   ```
4. Create a **read-only** access token at <https://huggingface.co/settings/tokens> → "Create new token" → role `read`. Copy it — you'll paste it as `HF_TOKEN` in the Space below.

## 2. Create the HuggingFace Space (Docker SDK)

1. <https://huggingface.co/new-space>
2. Owner: your username · Space name: e.g. `pharos` · License: `mit` · **SDK: Docker** · Visibility: **Public** (the API key gates it).
3. The Space gets its own git repo, e.g. `https://huggingface.co/spaces/<YOU>/pharos`.
4. Push this codebase to it (the `Dockerfile`, `start.sh`, `neuropharm/`, `static/`, `app.py` are all the Space needs).

   HuggingFace deprecated password-based git auth, so use **either** SSH **or** a write-token through the OS keychain — pick whichever matches your usual flow.

   **SSH (recommended if you already push to GitHub over SSH):**

   ```bash
   # one-time: add your public key to HF
   cat ~/.ssh/id_ed25519.pub | pbcopy   # or id_rsa.pub
   # paste at https://huggingface.co/settings/keys → "Add SSH key"

   cd /path/to/Pharos
   git remote add hf git@hf.co:spaces/<YOU>/pharos
   git push hf main
   ```

   Note the HF SSH URL format is `git@hf.co:spaces/<user>/<space>` — `hf.co` (not `huggingface.co`) and `spaces/` is a path segment.

   **Write token through OS keychain (HTTPS):**

   ```bash
   # Create a WRITE token at https://huggingface.co/settings/tokens
   # (a Read token will NOT work for git push)
   git config --global credential.helper osxkeychain   # macOS
   # or: git config --global credential.helper libsecret   # Linux GNOME
   # or: git config --global credential.helper manager     # Windows

   cd /path/to/Pharos
   git remote add hf https://huggingface.co/spaces/<YOU>/pharos
   git push hf main
   # username = your HF username, password = paste the write token
   # Future pushes skip the prompt — keychain remembers it.
   ```

5. The Space needs a **README.md with YAML frontmatter** so HF knows it's a Docker Space. Easiest path: open the Space's **Files** tab on the web, edit `README.md`, and replace its content with:

   ```markdown
   ---
   title: Pharos
   emoji: 🔬
   colorFrom: blue
   colorTo: indigo
   sdk: docker
   app_port: 7860
   pinned: false
   license: mit
   ---

   Pharos backend — see <https://github.com/aakri0/Pharos> for source.
   ```

   (HF's parser strips the frontmatter; GitHub will render it as a Jekyll-style block. If you don't want both repos to share the same README, keep them separate — push code to HF via a dedicated `hf` branch.)

## 3. Set Space "Secrets"

Space → **Settings** → **Variables and secrets** → add these as **Secrets** (not variables):

| Name | Value |
|---|---|
| `HF_TOKEN` | The read-only token you created in step 1.4 |
| `PHAROS_DB_REPO` | `<YOU>/pharos-drugbank` |
| `PHAROS_DB_FILENAME` | `drugbank_full.db` |
| `PHAROS_API_KEY` | A random string, e.g. `openssl rand -hex 24` |
| `PHAROS_ALLOWED_ORIGIN` | The Vercel URL once you have it, e.g. `https://pharos.vercel.app` (you can leave this blank for now and re-trigger the Space after step 5) |

The Space will rebuild on each secret change. First boot downloads the DB and logs `Downloaded /app/data/drugbank_full.db (~2,400 MB)` — that's the 5-10 min wait.

## 4. Verify the Space is up

The Space exposes itself at `https://<YOU>-<space-name>.hf.space`. Test with the API key:

```bash
curl -H "X-API-Key: <your PHAROS_API_KEY>" \
  https://<YOU>-pharos.hf.space/api/stats
# expect: {"drugs": 19842, "interactions": 2911156, "foodInteractions": 2552}
```

Without the key you should get `401 unauthorized`. If you get `Database not found`, the boot script couldn't reach the Dataset — recheck `HF_TOKEN` and `PHAROS_DB_REPO` spelling.

## 5. Deploy the Vercel frontend

1. Install the Vercel CLI: `npm i -g vercel`
2. From the repo root:

   ```bash
   vercel login                       # follow the prompt
   vercel --prod                      # accept defaults; Vercel picks up vercel.json
   ```

   Vercel will create a project (defaults to `pharos`) and give you a URL like `https://pharos.vercel.app`.

3. Tell the frontend where the backend is. Copy the template:

   ```bash
   cp static/config.example.js static/config.js
   ```

   Edit `static/config.js`:

   ```js
   window.PHAROS_API_BASE = "https://<YOU>-pharos.hf.space";
   window.PHAROS_API_KEY  = "<the PHAROS_API_KEY you set on the Space>";
   ```

   Then redeploy: `vercel --prod`.

4. **Back to the Space**: set `PHAROS_ALLOWED_ORIGIN` to your Vercel URL (e.g. `https://pharos.vercel.app`). The Space rebuilds. CORS is now locked to your frontend only.

## 6. Sanity-check the live demo

Visit your Vercel URL. The Drug picker should populate, the stats counter should show real numbers, and a RAG query like *"What happens if I take these together?"* on Apixaban + Ibuprofen should return the pair-interaction citation.

If the page loads but every panel says "checking" / "no analysis yet", open DevTools → Network and inspect any `/api/*` request:
- `401` → `PHAROS_API_KEY` mismatch between Space and `config.js`
- `CORS error` → `PHAROS_ALLOWED_ORIGIN` on the Space doesn't match your Vercel URL exactly (no trailing slash)
- `failed to fetch` → Space is sleeping; wait the cold-start window or hit `/api/stats` directly with curl to wake it

---

## Local development unchanged

Nothing about the above breaks local dev. Without any env vars, the server still binds to `127.0.0.1:8000`, reads `./drugbank_full.db`, and serves to a browser at the same origin with no API key required. The `config.js` file is gitignored, so the frontend bundle falls back to relative paths.
