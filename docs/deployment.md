# Deployment recipes

This page covers three deploy targets for the BidMate-DocAgent live
demo. All three serve the **Streamlit UI** (`demo/streamlit_app.py`)
backed by either the deterministic hashing pipeline (offline, free)
or live Claude synthesis (ADR 0011, paid).

For the CLI / eval flow (not deployment), see
[`docs/api-demo.md`](api-demo.md) and the root `README.md`.

## Pre-flight checklist

- [ ] `make smoke` passes locally — the demo runs the same pipeline.
- [ ] `data/index/index.json` exists (or the container will build it
      on first start — adds ~10 s cold start).
- [ ] You have decided whether to enable the live Anthropic backend.
      If yes, prepare `ANTHROPIC_API_KEY` and budget (~$0.05 per query
      with Sonnet 4.6 + prompt caching). If no, leave the default
      `BIDMATE_SYNTHESIS_BACKEND=stub` — the stub is a deterministic
      pass-through (ADR 0011).

## One-line `docker run` (no clone, fastest reviewer path)

For a reviewer who already has Docker installed, the fastest path is
a published image:

```bash
docker run --rm -p 8501:8501 -p 8000:8000 \\
  -e BIDMATE_DEMO_MODE=both \\
  ghcr.io/hskim-solv/bidmate-demo:latest
# Streamlit UI: http://localhost:8501
# FastAPI Swagger: http://localhost:8000/docs
```

The image is published via `make docker-publish` (requires `docker
login ghcr.io` beforehand). Override the tag with
`IMAGE_TAG=ghcr.io/<user>/bidmate-demo:<tag> make docker-publish` to
push to a different registry.

For the from-source recipe (clones the repo, builds locally), use
`make demo-docker` instead — same Dockerfile, same ports, no
registry dependency.

## Fly.io

Free tier comfortably hosts the demo (1 shared-CPU machine, 1 GB
RAM). [`fly.toml`](../fly.toml) at the repo root is the source of
truth — adjust `app`, `primary_region`, and `[[vm]].size` before
your first deploy.

```bash
# One-time
brew install flyctl                      # macOS
flyctl auth signup                       # or: flyctl auth login
flyctl launch --no-deploy --copy-config  # picks up fly.toml
flyctl apps create bidmate-docagent-demo # use the name you put in fly.toml

# Each deploy
flyctl deploy

# Optional: enable live Claude synthesis
flyctl secrets set ANTHROPIC_API_KEY=sk-ant-... \\
                   BIDMATE_SYNTHESIS_BACKEND=anthropic
```

Fly.io routes port 443 → container :8501 (Streamlit) and port 8000 →
container :8000 (FastAPI), so the UI lives at `https://<app>.fly.dev/`
and the API at `https://<app>.fly.dev:8000/docs`. The
`auto_stop_machines = true` setting lets the machine sleep when idle
to stay under the free-tier budget.

## Hugging Face Spaces

Spaces is ideal for a "click and try" reviewer link — no signup, no
billing, indexed by the AI community. The Streamlit SDK is supported
natively; the YAML frontmatter at the top of [`demo/README.md`](../demo/README.md)
is the Spaces config.

```bash
# Install the HF CLI
pip install --upgrade huggingface_hub
huggingface-cli login

# Create the Space (or do it in the web UI)
huggingface-cli repo create bidmate-docagent --type space --space-sdk streamlit

# Clone it locally, copy the repo in, push
git clone https://huggingface.co/spaces/<user>/bidmate-docagent space
rsync -av --exclude '.git' --exclude '.claude' --exclude 'data/index' \\
      --exclude 'reports' --exclude 'tests' --exclude 'eval' . space/
cd space && git add . && git commit -m "Initial sync" && git push
```

Spaces auto-detects `app_file: demo/streamlit_app.py` and runs
`streamlit run` on that path. The free tier provides 16 GB RAM /
2 CPU which is overkill for the hashing-backend demo. For live
Claude synthesis add `ANTHROPIC_API_KEY` and
`BIDMATE_SYNTHESIS_BACKEND=anthropic` in the Space's *Settings →
Variables and secrets*.

### Operational notes

The placeholder URL referenced from the repo-root README
(`https://huggingface.co/spaces/hskim-solv/bidmate-docagent`)
activates once the first push above succeeds. Day-to-day
operations:

- **Redeploy** — push to the Space's `main`; Spaces auto-rebuilds.
  Manual trigger via Space web UI *Settings → Restart this Space*
  (warm) or *Factory rebuild* (cold, re-installs requirements).
- **Dependency pinning** — Spaces picks up the repo-root
  [`requirements.txt`](../requirements.txt) automatically. The
  Streamlit / FastAPI / retrieval deps are pinned there; the
  heavier observability extras live in
  [`requirements-observability.txt`](../requirements-observability.txt)
  and are *not* pulled into the Space image, keeping cold-start
  under a minute.
- **Secrets rotation** — set `ANTHROPIC_API_KEY` and
  `BIDMATE_SYNTHESIS_BACKEND=anthropic` under *Settings → Variables
  and secrets*. Without them the demo runs the stub synthesis
  backend (ADR 0011 zero-regression: extractive and stub paths are
  byte-identical), so the Space remains functional even with no
  key.
- **Free-tier resource / cold-start** — 16 GB RAM / 2 CPU; the
  Space sleeps after inactivity and the first request after sleep
  takes ~30–60 s to wake. The index (`data/index/`) is committed,
  so no build step on cold-start.
- **Fallback when the Space is down** — the README "🚀 Live demo"
  table lists the one-line `docker run` and Colab quickstart
  immediately under the Spaces row, so a reviewer who hits a
  sleeping or unhealthy Space can pivot in one click.

## Railway

Railway picks up the `Dockerfile` automatically. The container ships
in `api` mode by default; set the deploy variable
`BIDMATE_DEMO_MODE=streamlit` to expose the Streamlit UI instead.

```bash
# Connect this repo to Railway
railway link        # or use the web UI
railway variables set BIDMATE_DEMO_MODE=streamlit
railway up

# Optional live LLM
railway variables set ANTHROPIC_API_KEY=sk-ant-... \\
                      BIDMATE_SYNTHESIS_BACKEND=anthropic
```

Railway's domain generator yields a URL like
`bidmate-docagent-demo.up.railway.app`. Pin a custom subdomain for
the portfolio link.

## Recording the demo video

A 2–3 minute screencast that closes the gap between *code review* and
*product reality* is the single highest-leverage portfolio asset
beyond the live URL itself.

Suggested storyboard (timestamps target ~150 s total):

1. **0:00–0:15** — open the live URL. Show the title, the three
   pipeline radio buttons, and the document list in the sidebar.
2. **0:15–0:45** — run `comparison_security_controls`
   (기관 A와 기관 B의 보안 요구사항 차이). Highlight the *balanced
   top-k* outcome (both agencies cited, no starvation) and the
   citation chunk_ids on each claim.
3. **0:45–1:15** — toggle "Compare extractive vs LLM synthesis".
   Show that under the `stub` backend the two columns are
   byte-identical (ADR 0011 zero-regression contract). Mention that
   `anthropic` backend would diverge here.
4. **1:15–1:45** — run `abstention_one_of_two_topic_overlap`
   (기관 A의 보안과 드론은?). Highlight `🔴 insufficient` status and
   the `Insufficiency` block. This is the **regression guard** for
   issue #89 — the demo proves the system *prefers abstaining* over
   guessing.
5. **1:45–2:15** — switch the sidebar to the Diagnostics tab on a
   prior result. Walk through the stage latency, the synthesis
   metadata, and the embedding backend display.
6. **2:15–end** — close with the README ablation table screenshot:
   bootstrap CIs visible, honest about which gaps are statistically
   real and which are noise.

Record with QuickTime / OBS at 1080p. Upload to YouTube (unlisted is
fine), then embed the link in `README.md` under the Live Demo
section.
