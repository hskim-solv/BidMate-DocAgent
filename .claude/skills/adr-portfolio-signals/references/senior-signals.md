# Senior Signal Rubric — `adr-portfolio-signals` reference

Verbatim source: [`docs/senior-positioning.md`](../../../../docs/senior-positioning.md) §시니어 시그널 1~5. 이 파일은 그 5개 signal을 ADR 한 개에 대해 `yes / partial / no` 판정할 수 있도록 probe 질문 + 흔한 partial 케이스 + false-positive 방지 노트를 정리한 rubric.

ADR을 평가할 때 5 signal 모두 순서대로 거친다 — 어떤 signal에 `no`가 나와도 다른 signal 평가는 그대로 계속.

---

## Signal 1 — 아키텍처 결정의 추적성

**Verbatim** ([`docs/senior-positioning.md:26-28`](../../../../docs/senior-positioning.md)): 각 ADR은 *하나의 의사결정*을 다룬다. status-tracked + supersession chain이 명시되어 load-bearing 선택과 그 진화가 사후 합리화 없이 추적 가능하다.

**Probe**:
- ADR이 *명시적 의사결정*을 잠그는가 (단순 정보 정리가 아니라)?
- supersession metadata 있는가 (`Supersedes` / `Superseded by` / `Extends` / `Refines` / `reuses pattern from`)?
- 다른 ADR을 명시적으로 참조하거나 강화/대체하는가?
- 결정의 reversal 조건이 명시되어 있는가 (예: ADR 0019의 4-condition re-open clause)?

**흔한 partial 케이스**:
- `proposed` 상태 — 결정이 *기록*은 됐지만 *잠금*은 미완. 위 조건 충족하면 `partial`로 표기, 사유는 `partial — proposed status, 결정은 기록됐으나 잠금 미완`.
- supersession 메타데이터 없는 단독 ADR — 시그널 자체는 yes지만 chain 강도는 약함. 그래도 yes.

**false-positive 방지**:
- 거의 모든 accepted ADR이 signal 1 = `yes`. `no`로 가는 경우는 사실상 없음 — ADR이 존재한다는 것 자체가 signal 1의 일부.

**Evidence 인용 우선순위**:
1. ADR 본문의 Status / Related / Supersedes 라인 (라인 번호 포함)
2. 본문에서 명시적으로 참조한 다른 ADR 번호
3. (선택) `docs/adr/README.md`의 status 표 행

---

## Signal 2 — 측정의 엄격성

**Verbatim** ([`docs/senior-positioning.md:64-84`](../../../../docs/senior-positioning.md)): 공개 합성 surface + 비공개 real-data surface 분리, bootstrap 95% CI, cross-machine SHA-256 결정성. "성능이 좋아졌다"의 정의가 surface별로 명시되고, README 숫자는 CI gate로 강제.

**Probe**:
- ADR이 *측정 정의*를 잠그는가 (어떤 metric을 어떤 표면에서 어떤 cadence로)?
- empirical threshold가 명시돼 있는가 (예: `full ≥+5pp`, bootstrap CI 비교, baseline-against-N 비교)?
- 공개 / 비공개 / cross-validation 표면 중 어느 곳에서 측정되는지 명시되어 있는가?
- "측정이 *왜* 이렇게 되어야 하는지"의 정당화가 있는가 (단순 metric 추가가 아니라)?

**흔한 partial 케이스**:
- `proposed` 상태이며 측정은 land 후 채워질 예정 → `partial — proposed, 측정은 land 후 채워질 예정`.
- ADR이 측정-gated deferral 패턴(ADR 0019/0025/0026 류) — 측정의 *부재*를 명시적으로 잠그는 경우. signal 2 자체는 `partial — 측정 deferred, 재오픈 조건 명시`로 표기. 측정의 *디자인*은 입증하므로 partial.
- CI에서 byte-equal fallback으로 골든이 유지되는 경우 (ADR 0023 HyDE 류) — public surface 측정은 의미 없지만 real-data 표면 측정 디자인이 명시되어 있으면 `partial`.

**false-positive 방지**:
- ADR이 "측정의 *엄격성* 디자인"이 아니라 "측정 *결과*"만 인용하는 경우 → signal 2가 아니라 signal 5 (재현성) 또는 signal 3 (실패 처리) 후보.
- governance 도구(`scripts/update_readme_metrics.py --check`) 자체는 signal 4 (governance-as-code). 측정 *방법론*을 정의하는 ADR이 signal 2.

**Evidence 인용 우선순위**:
1. `eval/config.yaml`, `eval/real_config.example.yaml` 참조 라인
2. bootstrap CI / SHA-256 / 결정성 언급 라인
3. 측정 threshold 라인 (예: `full ≥+5pp`)
4. ADR #0005 / ADR #0019 cross-ref (분리 표면 / deferral 패턴)

---

## Signal 3 — 실패를 시스템적으로 다룬다

**Verbatim** ([`docs/senior-positioning.md:86-96`](../../../../docs/senior-positioning.md)): 실패는 분류되고, 우선순위가 매겨지고, `tests/test_*_regression.py` regression gate로 잠긴다. `docs/real-data-failure-taxonomy.md`의 6 카테고리 + Decision Log entry로 회귀가 *다시* 발생하지 않게 잠금.

**Probe**:
- ADR이 특정 *실패 모드*에 응답하는가 (즉, "ADR이 *왜 지금* 필요한가"가 실패 경험에서 나오는가)?
- regression test 파일(`tests/test_*_regression.py`)이 ADR 본문에 명시적으로 언급되거나 추가되는가?
- failure taxonomy의 카테고리 (C1–C6) 또는 specific issue # (예: #69 → #89 false-abstention loop)를 인용하는가?
- Decision Log entry가 있거나 추가될 예정인가 (private-100-doc-experiments.md)?

**흔한 partial 케이스**:
- 새 ablation을 추가하는 ADR (ADR 0023 류) — 회귀 가드를 *작성*하지는 않지만 ADR 0001 invariance gate를 재사용 → `partial — 신규 ablation 추가, 기존 invariance gate(`tests/test_naive_baseline_ranking_invariance.py`) 재사용`.
- 측정 deferral ADR (0019/0025/0026) — 실패에 응답하기보다 측정 부재를 잠금 → 보통 `no — 회귀 사건 응답이 아님`.

**false-positive 방지**:
- "안전한 디자인"을 입증하는 ADR (예: prompt injection 방어, ADR 0008) — 회귀 *방지* 디자인이지만 *과거 실패*에 대한 응답이 명시적이지 않으면 `partial` 또는 `no`. issue # 또는 incident가 인용되어야 yes.
- ADR이 단순히 새 기능을 추가하는 경우 — 회귀 가드가 없으면 `no — 회귀 가드 미작성`.

**Evidence 인용 우선순위**:
1. `tests/test_*_regression.py` 파일명 + (가능하면) `:Lnn` 라인
2. ADR 본문에서 인용한 issue # (#69, #89 등)
3. failure taxonomy 카테고리 (C1–C6)
4. Decision Log entry 날짜

---

## Signal 4 — 거버넌스가 코드와 같이 진화한다

**Verbatim** ([`docs/senior-positioning.md:98-112`](../../../../docs/senior-positioning.md)): 규칙은 문서에만 있지 않고 *자동화로 강제*된다. PR template + pre-push hook + `scripts/_governance.py` SSoT + README sync gate + `branch-and-issue-check.yml` 등이 rule을 mechanically 잠근다.

**Probe**:
- ADR의 결정이 어떤 자동화(CI workflow, pre-push hook, script, 설정 파일)로 강제되는가?
- ADR이 example / gitignore / config 분리 convention을 정의하는가 (ADR 0005 류)?
- ADR 본문에 `scripts/`, `.github/workflows/`, `.githooks/`, `eval/config.yaml`, `Makefile` 같은 file path가 enforcement 메커니즘으로 등장하는가?
- 결정의 *위반*이 어떤 메커니즘으로 차단되는가 (CI fail / hook block / merge gate)?

**흔한 partial 케이스**:
- ADR이 새 디폴트만 정하고 enforcement는 다른 ADR/PR에 위임 → `partial — 디폴트 정의만, enforcement는 follow-up`.
- 자동화는 명시되어 있으나 아직 land되지 않은 경우 → `partial — enforcement 디자인 명시, 미구현`.

**false-positive 방지**:
- ADR이 단지 *어디서 측정한다*만 정의하는 경우 → signal 2 (측정 엄격성). 측정의 *gate 자동화*가 명시되어야 signal 4.
- ADR이 단지 *문서 컨벤션*만 정의하면 (예: 작성 가이드) signal 4의 강한 의미(자동화 강제)에 미달 → `no — 자동화 미명시` 또는 `partial — 컨벤션만, 자동화 미상`.

**Evidence 인용 우선순위**:
1. `.github/workflows/<file>.yml` 참조
2. `.githooks/<file>` 참조
3. `scripts/<file>.py --check` 참조 (CI gate scripts)
4. `eval/config.yaml`의 invariant key (예: `naive_baseline` ablation, `PIPELINE_CONFIG_KEYS`)
5. `scripts/_governance.py` `LOAD_BEARING_PATHS` 등록 여부

---

## Signal 5 — 재현 가능한 시연

**Verbatim** ([`docs/senior-positioning.md:114-130`](../../../../docs/senior-positioning.md)): 리뷰어가 클론 직후 한 명령(`make smoke` / `make reproduce`)으로 시스템을 돌릴 수 있고, 결정성(`hashing` backend) + cross-machine SHA-256으로 재현성 주장이 *증명 가능*한 형태로 backing된다.

**Probe**:
- ADR이 공개 surface에서 `make smoke` / `make reproduce` / 결정적 stub 디폴트로 동작하는가?
- 결정성 보장이 명시되어 있는가 (예: hashing backend, byte-equal golden, identity passthrough)?
- 외부 API / 네트워크 / 비밀키 없이 ADR이 정의한 표면이 돌아가는가?
- 결정의 *결과*가 SHA-256 가능한 산출물(eval_summary.json, naive_baseline_top_k.json 등)로 떨어지는가?

**흔한 partial 케이스**:
- public CI fallback이 byte-equal로 동작하지만 실측은 별도 표면에서 가능한 경우 (ADR 0023 HyDE) → `partial — 공개 CI는 fallback으로 byte-equal, 실측은 real-data 표면`.
- 결정 자체가 deferred되어 stub-identity 디폴트로 잠긴 경우 (ADR 0019/0025/0026) → `partial — stub default 결정성은 보존, 실측 deferred`.

**false-positive 방지**:
- 단순 `make` target 존재 — 그 target이 *결정적*이고 *공개 surface*에서 돌아야 yes. 비밀키 / 외부 API 필요하면 `partial`.
- ADR이 운영 데모(`docs/api-demo.md`)만 정의 — 그건 playground지 measurement source가 아니다 → signal 5 = `no` 또는 `partial — 데모 surface, measurement source 아님`.

**Evidence 인용 우선순위**:
1. `Makefile` (`make smoke`, `make reproduce`, `make ask`, `make demo` 등)
2. ADR 본문의 byte-equal / golden / deterministic 언급 라인
3. `EMBEDDING_BACKEND=hashing` 또는 결정적 stub backend 언급
4. `tests/data/*_golden.json` 또는 `tests/data/naive_baseline_top_k.json` 참조

---

## 판정 요약 cheat-sheet

| ADR 패턴 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| 측정-gated deferral (0019, 0025, 0026) | yes | partial — 측정 deferred | no — 회귀 응답 아님 | partial — 디폴트만 | partial — stub 결정성 |
| 신규 additive ablation (0011, 0023) | yes | partial — proposed | partial — invariance gate 재사용 | partial — 디폴트 정의 | partial — fallback byte-equal |
| 분리 표면 / 컨벤션 정의 (0005, 0007) | yes | yes(load-bearing) | partial — incident 인용시 yes | yes | partial |
| 실패 사건 응답 (#69 → #89 류) | yes | yes | yes | yes | partial |
| invariant 잠금 (0001, 0003) | yes | partial — 측정 자체 정의 아님 | yes — silent baselines rot 차단 | yes | yes |

이 표는 *판정의 출발점*일 뿐 — 실제 ADR 본문을 읽고 probe에 답한 결과가 우선.
