# Portfolio launch checklist

This is the **author-only** punch list for promoting BidMate-DocAgent
into a "click-and-try" portfolio piece. Issue [#172](https://github.com/hskim-solv/BidMate-DocAgent/issues/172)
groups the steps; some are wired in code (badges, asset slots,
Makefile targets), others are admin actions the author runs once
on GitHub or with their own recording tool.

## Code / asset wiring (already in place after PR #172)

- [x] Hero asset slot in `README.md` (top of file, above the badge row) — points at `docs/assets/demo.gif`.
- [x] Hero asset slot in `demo/README.md` — points at `docs/assets/demo.gif`.
- [x] `docs/assets/` directory exists (`.gitkeep`) so the asset has a stable home.
- [x] One-line `docker run` recipe + GHCR target (`make docker-publish`) — see [`docs/deployment.md`](deployment.md#one-line-docker-run-no-clone-fastest-reviewer-path).
- [x] Colab quickstart notebook + Open-in-Colab badge — see [`demo/bidmate_quickstart.ipynb`](../demo/bidmate_quickstart.ipynb).
- [x] Recording guide section in `docs/deployment.md#recording-the-demo-video`.

## Author actions (run once, not codable)

These cannot be done by a code change; they require the author's
GitHub account, local machine, and a few minutes per item.

### 1. Repo rename

The current name `BidMate-DocAgent` collides with the parked
`bidmate.co.kr` brand. Pick a final name and rename **once**:

```bash
# On GitHub: Settings → General → Repository name → Rename
# Then locally:
git remote set-url origin git@github.com:<user>/<new-name>.git
```

After rename, search-replace the old name in:

- `README.md` (badge URLs, repo references, hero asset path comments)
- `demo/README.md` (HF Spaces YAML — `title:` field)
- `demo/bidmate_quickstart.ipynb` (the `!git clone` URL)
- `docs/deployment.md` (Fly.io / HF Spaces / Railway recipes)
- `Makefile` (`IMAGE_TAG ?= ghcr.io/<user>/bidmate-demo:latest`)
- `.github/workflows/*.yml` (any hardcoded repo references)

A single follow-up PR per rename is the safest path — the search-replace
diff is large but mechanical.

### 2. GitHub profile pin

Pin the repo to the author's profile so it shows on the public profile
page:

- GitHub → click the profile picture → **Your profile** → **Customize
  your pins** → tick the renamed repo → **Save pins**.

Pinned repos render the first README section as a card preview, so the
hero asset (below) is what reviewers see in the profile grid.

### 3. Record the demo asset

A 60–90 second walkthrough is enough. Two recommended formats:

**A. asciinema cast (terminal demo)**

```bash
asciinema rec docs/assets/demo.cast
# inside the recording session:
make index
make demo
# open http://localhost:8501 in another tab, run a query
# Ctrl-D to stop recording
```

Convert to GIF if desired:

```bash
# npm install -g asciicast2gif
asciicast2gif docs/assets/demo.cast docs/assets/demo.gif
```

**B. screen recording (UI demo)**

Record at 1280×720 with QuickTime / OBS, trim to 60–90 s, export as
MP4 or GIF, save to `docs/assets/demo.gif` (or `.mp4`). Keep file size
under 5 MB for the README to render quickly.

### 4. Publish the GHCR image (one-time)

The `docker run ghcr.io/<user>/bidmate-demo:latest` recipe in the
README only works if the image is pushed:

```bash
docker login ghcr.io        # use a PAT with write:packages scope
make docker-publish         # builds + pushes ghcr.io/hskim-solv/bidmate-demo:latest
```

After the first push, the image is **public** by default for new
GHCR pushes; if the author had set it private, flip it via
**GitHub → Packages → bidmate-demo → Package settings → Change visibility**.

### 5. Update live demo URL in README

Once the Fly.io / HF Spaces deploy is up, replace the placeholder
"배포 가이드: [`docs/deployment.md`](deployment.md)" cell in the
"🚀 Live demo" table with the actual URL:

```markdown
| **Streamlit UI** | [bidmate-docagent-demo.fly.dev](https://bidmate-docagent-demo.fly.dev) | ... |
```

## Verification (after all actions)

- [ ] README hero asset renders on GitHub (the .gif or .mp4 plays inline).
- [ ] Open-in-Colab badge opens the notebook in colab.research.google.com and the 5 cells run green.
- [ ] `docker run ghcr.io/<user>/bidmate-demo:latest` boots the demo on a clean machine.
- [ ] Live demo URL responds 200 and the radio buttons (`naive_baseline` / `agentic_full` / `agentic_full_llm`) all return grounded answers.
- [ ] Repo is pinned on the author's GitHub profile.
