# 0052: real100 Eval Hardcase 확장 — LLM-Assisted Generator + n=21→221

| Field       | Value                                                       |
|-------------|-------------------------------------------------------------|
| **Status**  | Proposed                                                    |
| **Date**    | 2026-05-17                                                  |
| **Issue**   | #942                                                        |
| **Authors** | hskim-solv                                                  |
| **Tags**    | eval, real-data, dataset-cardinality, hardcase, distinguishing-power |
| **Supersedes** | ADR 0044 (incremental n≥30/n≥50 trajectory)              |

## TL;DR

- ADR 0052: real100 eval 케이스 **n=21 → n=221** 점프 확장 (100 doc × 신규 200 hardcase + 기존 21 케이스 유지)
- 생성 방법: `scripts/generate_real_cases.py` (Anthropic SDK, ADR 0052 prep 으로 PR #936 머지) — hardcase-only 정책 (5 enum: distractor_heavy / ambiguous_query / multi_hop / no_answer / long_context)
- ADR 0044 의 incremental trajectory (`n≥30` → `n≥50`) 대체 — 100-doc 코퍼스에서 **distinguishing-power floor** (PR-5a / ADR 0053 의 random + single_chunk) 와 의미있는 delta 측정 가능한 n 으로 직접 점프

## 배경

### ADR 0044 의 한계

ADR 0044 는 n=21 → n≥30 → n≥50 의 점진 trajectory 로 통계 신호를 회복하려 했다. n≥50 의 Wilson 95% CI 는 ±14pp 로 좁아지지만 (ADR 0044 §목표 cardinality):

- **변별력 측정 (ADR 0053 신설 게이지) 에는 여전히 부족.** `random_retrieval` 와 `single_chunk` 의 메트릭 vs default 의 ~5-10pp gap 을 noise floor 위로 띄우려면 n ≥ ~150 필요.
- **Hardcase 비율 부재.** 기존 21 케이스의 다수가 single-hop factual lookup — 평이한 쿼리에서 default 가 ceiling 에 가까워 ablation 비교 가치가 0 에 수렴.
- **수동 작성 비용.** Operator 가 매번 손으로 케이스 작성하는 incremental n+9 / n+29 사이클은 ROI 가 낮다.

### Step-change 선택

- **#936 (PR-A) 머지로 LLM-assisted generator (`scripts/generate_real_cases.py`) 인프라 완비** — Anthropic Sonnet 4-6 로 100 doc 각 2 case 생성, hardcase-only 정책 prompt 강제, stub backend 로 schema regression 보호.
- **n=200 한 번에 jump** 가 incremental n+9 보다 비용 효율적 (LLM cost ~$2 + 사용자 review ~2h 1회 vs 매번 수동 작성).
- **PR-5a (ADR 0053) 머지로 distinguishing-power floor (random + single_chunk) 인프라 완비** — 본 ADR 의 n=221 baseline 이 PR-5b (`scripts/distinguishing_power.py`) 의 첫 measurement surface 가 됨.

## 결정

ADR 0044 의 incremental trajectory 대체. real-eval 케이스 cardinality 를 **n=21 → n=221** 로 직접 확장:

1. **신규 200 hardcase**: `scripts/generate_real_cases.py` 으로 100 doc 각 2 case 생성. 5 enum (`distractor_heavy` / `ambiguous_query` / `multi_hop` / `no_answer` / `long_context`) 분포 target. 평범한 fact-lookup 쿼리 (사업기간 / 예산 단순 lookup) 명시 금지.
2. **기존 21 케이스 유지**: cross-version 회귀 신호 보존. baseline 의 byte-level reproducibility 침해 없음.
3. **3 ablation_runs**: `full` (default agentic_full + flat), `random_retrieval` (default + retrieval_backend=random, ADR 0053), `single_chunk` (pipeline=single_chunk preset, ADR 0053).
4. **baseline 1회 commit**: `reports/real100/baseline.aggregate.json` 을 n=221 시점 1회 regen 후 ADR 0044 §결과 의 update protocol (= `make real-eval-baseline-update`) 그대로 유지.
5. **케이스 정의 gitignored 유지**: `eval/real_config.local.yaml` 은 ADR 0005 의 private 경계 보존 — aggregate-only 공개.

### 분포 target (5 enum)

생성 결과 (Claude Sonnet 4-6, temperature=0, prompt 강제):

| Enum                | n   | 비율 |
|---------------------|-----|------|
| `no_answer`         | 101 | 50.5% |
| `multi_hop`         | 95  | 47.5% |
| `distractor_heavy`  | 47  | 23.5% |
| `long_context`      | 16  | 8.0% |
| `ambiguous_query`   | 2   | 1.0% |

**관찰**: `no_answer` + `multi_hop` 비중이 크고 `ambiguous_query` 가 sparse — 후속 라운드에서 generator instruction 재조정 가능. 본 ADR 은 첫 generation 의 distribution 을 **as-is** 로 baseline 화 (artificial rebalancing 비결정 + reproducibility 깸).

## 결과

### Positive

- **Distinguishing-power floor 측정 가능** — PR-5b (`scripts/distinguishing_power.py`) 가 default vs random_retrieval vs single_chunk 의 quality gap 을 noise floor 위로 띄울 수 있음.
- **Portfolio claim 직접화** — "real 100-doc RFP × 221 hardcase 에서 RAG default 가 random 대비 N% 우위" 가 외부 청자 (recruiter / engineer reviewer) 에게 직접 의미있는 진술.
- **합성 surface (PR-7 dropped) 와 분리.** 합성 ceiling-saturation 문제와 무관한 real-data 변별력 회복.
- **재생성 cost 0** — `scripts/generate_real_cases.py` 와 stub backend 로 향후 라운드도 같은 인프라.

### Negative

- **Baseline metric shift** — n=21 → n=221, hardcase-only 정책 → 모든 quality 메트릭이 by-definition 변동. 본 PR 은 `[ALLOW_REGRESSION]` 게이트 필수.
- **LLM 비결정성 의존** — generator 가 deterministic (temperature=0 + SHA-stable prompt) 이지만 모델 weights 자체는 외부. 향후 모델 update 가 케이스 drift 유발 가능 → 케이스셋은 1회 생성 후 `eval/real_config.local.yaml` 에 frozen.
- **분포 불균형** — `ambiguous_query` n=2 는 per-enum 분석 불가. ADR 0053 의 distinguishing-power 측정은 전체 aggregate 만 의미있음 (per-enum slice 는 후속 라운드 필요).
- **Local case 작성 1회성 비용** — ~$2 LLM + ~30분 사용자 승인 (실제 측정: 200/200 auto-pass, 1 case 만 query_type 자동 정정).

### Invariance check

- **ADR 0001** (naive_baseline preset 불변): 영향 없음 — 공개 합성 eval surface 미변경.
- **ADR 0003** (answer contract schema_version=2): 영향 없음 — 답변 계약 미변경.
- **ADR 0005** (eval-split public/private 경계): **보존** — 케이스 정의는 gitignored `eval/real_config.local.yaml` 에만; aggregate 만 `reports/real100/baseline.aggregate.json` 으로 공개.
- **ADR 0030** (leaderboard silence threshold n-aware): 자동 적용 — n=221 에서 `δ_silence = max(5e-4, 0.5/221) ≈ 2.3e-3` 으로 tighten.
- **ADR 0044**: **Superseded** — 본 ADR 이 incremental trajectory 를 step-change 로 대체.
- **ADR 0053** (distinguishing-power floor: random + single_chunk): 첫 measurement surface 로 본 baseline 사용.

## 검토한 대안

| 대안 | 거부 사유 |
|---|---|
| **ADR 0044 그대로 유지 (n≥50 incremental)** | n≥50 의 ±14pp CI 는 ADR 0053 의 default vs floor gap (예상 5-10pp) 보다 큼 — distinguishing-power 측정 불가. |
| **n=200 정확히 (기존 21 폐기)** | Cross-version 회귀 신호 손실. 기존 21 케이스는 ADR 0044 baseline 비교 anchor 로 유지 가치 있음. |
| **수동 200 케이스 작성** | 사용자 ~6h × 200 case = 작성-자체로 portfolio cost 가 ROI 초과. PR-A 의 LLM-assisted generator 인프라가 30분 + ~$2 로 대체. |
| **Synthetic surface 확장 (ADR 0050 의 H/I/J/K corpus 활용)** | 합성 ceiling-saturation 별 surface — real 변별력 회복과 직교한 문제. 별 Phase 2 안건. |
| **per-enum 균등 분포 강제 (각 40 cases)** | Generator 가 5 enum 균등 생성하도록 prompt 강제하면 일부 doc 의 의미있는 hardcase 가 enum-quota 때문에 strip. 첫 라운드는 자연 분포 수용, distribution 후속 라운드에서 조정. |

## Verification

<!-- verifies-key: reports/real100/baseline.aggregate.json:num_predictions -->
<!-- verifies-key: scripts/generate_real_cases.py:HARDCASE_ENUMS -->
<!-- verifies-key: docs/adr/0044-realN-eval-case-expansion.md:Superseded by -->

## 참조

- ADR 0001 — naive_baseline 불변량 (영향 없음)
- ADR 0003 — 답변 계약 schema_version=2 (영향 없음)
- ADR 0005 — eval 분리 public/private 경계 (보존)
- ADR 0030 — 리더보드 silence threshold n-aware 공식
- ADR 0044 — real100 in-place n 증가 정책 (**Superseded by 본 ADR**)
- ADR 0053 — distinguishing-power floor (`random` retrieval + `single_chunk` preset) — 본 baseline 의 측정 대상
- PR #936 — `scripts/generate_real_cases.py` LLM-assisted generator (PR-A)
- PR #939 — `random` backend + `single_chunk` preset (PR-5a)
- Issue #942 — 본 ADR 구현 추적
