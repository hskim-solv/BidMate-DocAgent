# 배포 레시피

이 페이지는 BidMate-DocAgent 라이브
데모를 위한 세 가지 배포 타깃을 다룬다. 셋 모두 **Streamlit UI**
(`demo/streamlit_app.py`)를 서빙하며, 결정론적 hashing 파이프라인(오프라인, 무료)
또는 라이브 Claude synthesis(ADR 0011, 유료)로 뒷받침된다.

> **정식 라이브 데모는 Hugging Face Spaces** 다
> (`https://huggingface.co/spaces/hskim-solv/bidmate-docagent`). Fly.io
> 자동 재배포는 현재 **보류(parked)** — depot.dev 리모트 빌더 i/o timeout
> 으로 2026-05-26 이후 연속 실패했다. Fly 앱·config 는 보존하되 destroy
> 하지 않으며, `deploy-fly.yml` 의 `if: false` 한 줄을 제거하면 부활한다
> (issue #1784).

CLI / eval 흐름(배포 아님)에 대해서는
[`docs/operations/api-demo.md`](./api-demo.md) 와 루트 `README.md` 를 참조하라.

## Pre-flight 체크리스트

- [ ] `make smoke` 가 로컬에서 통과 — 데모는 같은 파이프라인을 실행한다.
- [ ] `data/index/index.json` 이 존재(또는 컨테이너가 첫 시작 시
      빌드한다 — cold start 에 ~10 s 추가).
- [ ] 라이브 Anthropic 백엔드를 활성화할지 결정했다.
      그렇다면 `ANTHROPIC_API_KEY` 와 예산(Sonnet 4.6 + prompt caching
      으로 쿼리당 ~$0.05)을 준비한다. 아니라면 기본
      `BIDMATE_SYNTHESIS_BACKEND=stub` 을 둔다 — stub 은 결정론적
      pass-through 다(ADR 0011).

## 한 줄 `docker run` (clone 불필요, 가장 빠른 리뷰어 경로)

이미 Docker 가 설치된 리뷰어에게 가장 빠른 경로는
publish 된 이미지다:

```bash
docker run --rm -p 8501:8501 -p 8000:8000 \\
  -e BIDMATE_DEMO_MODE=both \\
  ghcr.io/hskim-solv/bidmate-demo:latest
# Streamlit UI: http://localhost:8501
# FastAPI Swagger: http://localhost:8000/docs
```

이미지는 `make docker-publish` 로 publish 된다(사전에 `docker
login ghcr.io` 필요). 다른 레지스트리로 push 하려면
`IMAGE_TAG=ghcr.io/<user>/bidmate-demo:<tag> make docker-publish` 로
태그를 override 한다.

소스로부터 빌드하는 레시피(repo 를 clone 하고 로컬에서 빌드)는
대신 `make demo-docker` 를 사용한다 — 같은 Dockerfile, 같은 포트,
레지스트리 의존성 없음.

## Fly.io

무료 티어가 데모를 넉넉히 호스팅한다(shared-CPU 머신 1대, 1 GB
RAM). repo 루트의 [`fly.toml`](../../fly.toml) 이 진실의
출처다 — 첫 배포 전에 `app`, `primary_region`, `[[vm]].size` 를 조정하라.

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

Fly.io 는 포트 443 → 컨테이너 :8501 (Streamlit) 과 포트 8000 →
컨테이너 :8000 (FastAPI) 로 라우팅하므로, UI 는 `https://<app>.fly.dev/` 에,
API 는 `https://<app>.fly.dev:8000/docs` 에 있다.
`auto_stop_machines = true` 설정은 idle 시 머신이 sleep 하게 해
무료 티어 예산 내에 머물게 한다.

### 지속적 배포(continuous deploy) — ⏸️ 현재 보류(parked)

> **이 워크플로는 `deploy-fly.yml` 의 `deploy` job 에 `if: false` 가 걸려
> 비활성이다.** depot.dev 리모트 빌더 i/o timeout (`deadline_exceeded ...
> api.depot.dev`, exit 126)으로 2026-05-26 이후 모든 run 이 실패했다. 정식
> 라이브 데모는 HF Spaces 다. 부활하려면 빌더 문제를 해결한 뒤 job 의
> `if: false` 를 제거한다. 아래는 부활 시의 동작 설명이다.

런타임 경로를 건드리는 `main` 으로의 모든 push 는
[`.github/workflows/deploy-fly.yml`](../../.github/workflows/deploy-fly.yml)
을 실행해 라이브 데모를 재배포한다. 경로 필터는 Dockerfile 의
COPY 집합을 미러링한다: 모든 top-level `*.py`, `api/**`, `demo/**`,
`scripts/build_index.py`, `eval/fixtures/smoke_rfp/raw/**`, `data/lexicon/**`,
컨테이너 primitive(`Dockerfile`, `docker-entrypoint.sh`,
`requirements.txt`, `fly.toml`), 그리고 workflow 자체. doc 전용
변경은 배포를 트리거하지 *않는다*. workflow 는 `flyctl status --json`
으로 모든 머신이 `started` 상태인지 단언하고
머지된 PR 에 라이브 URL + short SHA 코멘트를 게시하기 전에
`https://<app>.fly.dev/health` 를 smoke-test 한다.

일회성 셋업: `FLY_API_TOKEN` 을 repository secret 으로 추가한다
(로컬에서 `flyctl auth token`, 그다음 Repo Settings → Secrets and
variables → Actions → New secret).

### 롤백

릴리스가 회귀를 도입하면:

```bash
flyctl releases                              # list recent releases (version, status, time)
flyctl releases revert <version>             # roll back to a specific release
flyctl status                                # confirm machines pinned to the reverted release
```

revert 된 상태는 다음 push 가 필터된 경로를 건드릴 때까지
sticky 하다. 코드 변경 없는 수동 재배포는 workflow 의
`workflow_dispatch` 트리거(Actions tab → *Deploy demo to Fly.io* →
*Run workflow*)를 사용한다; `dry_run: true` 로 설정하면 릴리스 없이
이미지만 빌드한다 — 머지 전 `Dockerfile` 변경 검증에 유용하다.

## Hugging Face Spaces

Spaces 는 "클릭해서 써보는" 리뷰어 링크에 이상적이다 — 가입 불필요,
빌링 불필요, AI 커뮤니티가 인덱싱. Streamlit SDK 가 네이티브로
지원된다; [`demo/README.md`](../../demo/README.md) 상단의 YAML frontmatter
가 Spaces 구성이다.

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

Spaces 는 `app_file: demo/streamlit_app.py` 를 auto-detect 하고 그 경로에서
`streamlit run` 을 실행한다. 무료 티어는 16 GB RAM /
2 CPU 를 제공하는데, hashing-backend 데모에는 과하다. 라이브
Claude synthesis 의 경우 Space 의 *Settings →
Variables and secrets* 에 `ANTHROPIC_API_KEY` 와
`BIDMATE_SYNTHESIS_BACKEND=anthropic` 을 추가한다.

### 운영 노트

repo 루트 README 에서 참조하는 placeholder URL
(`https://huggingface.co/spaces/hskim-solv/bidmate-docagent`)은
위 첫 push 가 성공하면 활성화된다. 일상
운영:

- **재배포** — Space 의 `main` 으로 push; Spaces 가 자동 재빌드한다.
  Space 웹 UI *Settings → Restart this Space* (warm) 또는
  *Factory rebuild* (cold, requirements 재설치)로 수동 트리거.
- **의존성 고정(pinning)** — Spaces 는 repo 루트
  [`requirements.txt`](../../requirements.txt) 를 자동으로 가져온다.
  Streamlit / FastAPI / retrieval 의존성이 거기 고정된다;
  더 무거운 observability extras 는
  [`requirements-observability.txt`](../../requirements-observability.txt)
  에 있으며 Space 이미지로 끌려오지 *않아*, cold-start 를
  1분 미만으로 유지한다.
- **Secrets 로테이션** — *Settings → Variables
  and secrets* 아래에 `ANTHROPIC_API_KEY` 와
  `BIDMATE_SYNTHESIS_BACKEND=anthropic` 을 설정한다. 이것들 없이는 데모가
  stub synthesis 백엔드를 실행하므로(ADR 0011 zero-regression: extractive
  와 stub 경로는 byte-identical), 키가 없어도 Space 는 작동
  상태를 유지한다.
- **무료 티어 리소스 / cold-start** — 16 GB RAM / 2 CPU; Space 는
  비활동 후 sleep 하며 sleep 후 첫 요청은 깨어나는 데
  ~30–60 s 걸린다. 인덱스(`data/index/`)는 커밋되어 있어
  cold-start 에 빌드 단계가 없다.
- **정식 라이브 데모 + fallback** — HF Spaces 가 **정식** 라이브
  데모다(Fly.io 는 보류). Space 가 sleeping 이거나 unhealthy 하면 README
  "라이브 데모" 표의 한 줄 `docker run` 또는 Colab quickstart 로 한 번의
  클릭에 전환할 수 있다.

## Railway

Railway 는 `Dockerfile` 을 자동으로 가져온다. 컨테이너는 기본적으로
`api` 모드로 배송된다; 대신 Streamlit UI 를 노출하려면 deploy 변수
`BIDMATE_DEMO_MODE=streamlit` 을 설정한다.

```bash
# Connect this repo to Railway
railway link        # or use the web UI
railway variables set BIDMATE_DEMO_MODE=streamlit
railway up

# Optional live LLM
railway variables set ANTHROPIC_API_KEY=sk-ant-... \\
                      BIDMATE_SYNTHESIS_BACKEND=anthropic
```

Railway 의 도메인 생성기는
`bidmate-docagent-demo.up.railway.app` 같은 URL 을 만든다. 포트폴리오
링크용으로 커스텀 서브도메인을 고정하라.

<a id="recording-the-demo-video"></a>

## 데모 비디오 녹화

*코드 리뷰* 와 *제품 현실* 사이의 간극을 메우는 2–3분
스크린캐스트는 라이브 URL 자체를 넘어선 단일
최고 레버리지 포트폴리오 자산이다.

권장 스토리보드(타임스탬프는 총 ~150 s 목표):

1. **0:00–0:15** — 라이브 URL 을 연다. 타이틀, 세 개의
   파이프라인 라디오 버튼, 사이드바의 문서 목록을 보여준다.
2. **0:15–0:45** — `comparison_security_controls`
   (기관 A와 기관 B의 보안 요구사항 차이)를 실행한다. *balanced
   top-k* 결과(두 기관 모두 인용, starvation 없음)와 각 claim 의
   citation chunk_id 를 강조한다.
3. **0:45–1:15** — "Compare extractive vs LLM synthesis" 를 토글한다.
   `stub` 백엔드에서 두 컬럼이
   byte-identical 함을 보여준다(ADR 0011 zero-regression 계약).
   `anthropic` 백엔드는 여기서 갈라질 것이라고 언급한다.
4. **1:15–1:45** — `abstention_one_of_two_topic_overlap`
   (기관 A의 보안과 드론은?)를 실행한다. `🔴 insufficient` 상태와
   `Insufficiency` 블록을 강조한다. 이것은 issue #89 의 **회귀
   가드** 다 — 데모는 시스템이 추측보다 *보류(abstaining)를 선호*함을
   증명한다.
5. **1:45–2:15** — 이전 결과에서 사이드바를 Diagnostics 탭으로
   전환한다. 다음을 짚는다:
   - stage latency (`diagnostics.stage_latency` 의 스테이지별 ms),
   - synthesis 메타데이터 — 특히 `diagnostics.synthesis.cost_estimate_usd`
     와 `cache_read_tokens` / `cache_write_tokens` (ADR 0015 cost
     telemetry; 반복 쿼리에서 `cache_read_tokens > 0` 을 보여줌으로써
     caching 이 실제로 발화함을 증명),
   - embedding 백엔드 표시.
6. **2:15–2:45** — README ablation 표 스크린샷으로 마무리한다:
   bootstrap CI 가 보이고, 어느 갭이 통계적으로 진짜이고 어느 것이
   노이즈인지 정직하게.
7. **2:45–end (선택 30s 에필로그)** — 터미널로 전환,
   `BIDMATE_LOG_FORMAT=json make demo` 를 한 번 실행해 구조화된
   `query_start` / `query_complete` JSON 이벤트를 보여준 뒤,
   `make reproduce` 로 SHA-256 재현성 해시
   (ADR 0005 표면)를 출력한다 — public fixture smoke 표면이
   호스트 전반에 결정론적임을 증명한다.

QuickTime / OBS 로 1080p 로 녹화한다. YouTube 에 업로드(unlisted 도
괜찮음)하고, Live Demo 섹션 아래 `README.md` 에 링크를
임베드한다. 동반 정지 이미지 자산(`docs/assets/demo.gif`,
< 8MB)은 단계 2 와 4 만 집중한 30-60s 루프일 수 있다 — 이것이
60초 리뷰어 인상에 가장 신호가 강한 슬라이스다.
