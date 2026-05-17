# 0029: Real-data case proposer를 additive semi-supervised eval-set 성장 표면으로

- **Status**: proposed
- **Date**: 2026-05-13
- **Related**: [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) / [ADR 0006](./0006-llm-judge-on-real-data-only.md) 확장; [ADR 0011](./0011-llm-synthesis-as-additive-ablation.md) / [ADR 0012](./0012-llm-judge-on-public-synthetic.md) backend 패턴 재사용; [ADR 0001](./0001-preserve-naive-baseline.md) / [ADR 0003](./0003-structured-answer-citation-contract.md) / [ADR 0004](./0004-verifier-retry-policy.md) / [ADR 0008](./0008-evidence-boundary.md) 보존; calibration은 [ADR 0016](./0016-judge-human-agreement.md) mirror
- **Deciders**: hskim

## TL;DR

- private real-data eval 표면(`eval/real_config.example.yaml`)이 human label N=100에 cap — case당 5-15분 → N=200+는 라벨링 처리량 문제.
- **case proposer**(stub-default + opt-in live backend)가 후보 case 생성 → 사람이 검토(accept/edit/reject) 후 `eval/real_config.local.yaml` append.
- ADR 0005 aggregate-only 경계 보존: case body는 commit boundary 통과 금지; `proposer.aggregate.json`만 commit.

## 배경

private real-data eval 표면([`eval/real_config.example.yaml`](../../eval/real_config.example.yaml))은 human label만큼 cap — 현재 N=100. 각 case는 8-field dict(`query`, `query_type`, `expected_doc_ids`, `expected_terms`, `expected_citation_terms`, `expected_claim_targets`, `answerable`, `id`) — 작성에 5-15분. N=200+ 확장은 라벨링 처리량 문제, 인프라 문제 아님.

[ADR 0005](./0005-eval-split-public-synthetic-private-local.md)가 case body를 commit 경계 밖 lock(aggregate-only). [ADR 0006](./0006-llm-judge-on-real-data-only.md)이 real-data 표면에 LLM 허용하되 *judge*(기존 답변 second-opinion read)에 한정. "LLM이 case 후보 제안, 사람이 검토"는 어느 ADR 범위도 아님; 명시 결정 없이 수행은 ADR 0005가 ground truth로 다루는 표면에 기계 생성 label silently mix.

적합 패턴은 ADR 0011 *additive 분석 변형*: 기존 표면의 계약을 건드리지 않고 신규 표면(stub-default backend, opt-in live backend) 도입. ADR 0012가 이미 합성 judge에 적용. 동일 shape가 real-data case proposer에 적용 — 단 두 추가 제약: case body는 여전히 commit 경계 통과 불가(ADR 0005) + 사람 reviewer가 `eval/real_config.local.yaml` 진입 결정 gate.

## 결정

real-data eval에 additive, semi-supervised 입력 표면으로 **case proposer** 추가. proposer가 `eval/real_config.example.yaml` 8-field schema와 매치되는 후보 case dict 생성; 사람이 각 후보 검토(accept / edit / reject) 후에 `eval/real_config.local.yaml` append.

### 계약

- **Input**: `data/data_list.csv` 메타데이터 + `data/index/real100/index.json`에서 각 seed 문서의 top-3 chunk. `live` backend는 chunk body 소비 가능; 결정적 필드(`expected_doc_ids`, `answerable`)는 *항상* source row + `query_type`에서 derive — 모델 응답에서 derive 안 함.
- **Output (per case)**: 8-field schema + 2 meta field superset:
  ```yaml
  - id: proposed_<YYYYMMDD>_<NNN>
    source: "proposed-then-reviewed"          # vs. "human"
    proposer_meta:
      backend: "stub" | "openai_compatible"
      model: "<model-id or 'stub'>"
      seed_doc_id: "<doc-id from index>"
      generated_at: "<ISO8601Z>"
      proposer_version: 1
    # ... 8 schema fields ...
  ```
  `source` + `proposer_meta` 양쪽 모두 `eval/real_config.local.yaml` append 시 strip → active config는 기존 schema의 byte-equal subset 유지.
- **Committable aggregate** (`reports/proposed/proposer.aggregate.json`, ADR 0005 allowlist):
  ```json
  {
    "schema_version": 1,
    "backend": "stub" | "openai_compatible",
    "n_proposed": 30, "n_reviewed": 25, "n_accepted": 18,
    "proposer_accept_rate": 0.72,
    "field_edit_rate": {"query": 0.40, "expected_terms": 0.65, ...},
    "by_query_type": {"single_doc": {...}, "abstention": {...}}
  }
  ```
  per-case proposed / reviewed yaml은 `reports/proposed/*.local.yaml`(gitignored) 잔류.

### Backend pluggability

`eval/case_proposer.py`가 `eval/synthetic_judge.py` backend dispatch mirror:

- `stub`(default) — 결정적; `data_list.csv` row에서 메타데이터 driven template 쿼리(`사업기간` / `사업예산` / abstention) 출력. run 간 byte-equal. 테스트 + CI plumbing 사용.
- `openai_compatible` — 일반 OpenAI-compatible endpoint. 기존 `BIDMATE_JUDGE_API_KEY` / `BIDMATE_JUDGE_MODEL` / `BIDMATE_JUDGE_BASE_URL` env var 재사용(단일 모델이 judge + proposer 양쪽 serve 가능); backend 선택은 별도 var(`BIDMATE_CASE_PROPOSER_BACKEND`) → 두 표면 독립 토글. chunk body는 prompt 도달 전 `neutralize_instruction_patterns` + `EVIDENCE_BOUNDARY`(ADR 0008) 통과.

### 2-stage human gate

- `make case-propose`가 `reports/proposed/proposed_cases.local.yaml` write.
- `make case-review`는 각 후보 walk + yaml diff 표시 + `approved: true|false` + edit을 `reports/proposed/reviewed_cases.local.yaml`에 record하는 interactive CLI.
- `make case-promote`가 approved case를 `eval/real_config.local.yaml`에 *idempotent* append, 이미 존재하는 `id` skip. promote step은 명시(review가 auto-trigger 아님) → 사람이 한 번 더 확인.
- `make case-proposer-aggregate`가 reviewed yaml에서 `proposer.aggregate.json` 계산.

### 통계적 hygiene

- active `run_eval.py` aggregate는 `source` 필드(`human` vs `proposed-then-reviewed`) **노출 안 함**. `eval/real_config.local.yaml` 모든 case가 downstream 파이프라인에 동등 authoritative 취급. mix 비율은 `proposer.aggregate.json` + README "100 hand + N proposed-reviewed" 2-column 렌더링에서만 가시. headline eval 표면이 정직 + 라벨링 provenance auditable 유지.
- `proposer_accept_rate`는 calibration knob, ADR 0016 `judge_human_agreement` 병렬: < 0.5는 proposer가 체계적으로 rejected case 생산 → backend / prompt 재고, numeric gate 아님.

### 주기

real-data cycle 나머지와 동일 수동. 사용자가 case set 성장 원할 때 `make case-propose && make case-review && make case-promote` 실행 → `make real-eval`이 (이제 더 큰) `eval/real_config.local.yaml`에 파이프라인 재실행.

## 결과

**Wins**

- ADR 0005 깨지 않고 real-data N을 100 초과 성장 — case body는 commit 경계 통과 안 함.
- proposer가 competent해지면 per-case 라벨링 시간 5-15분(full hand-label) → 1-3분(review + edit) 감소, `proposer_accept_rate`가 competence 측정.
- ADR 0011 "stub-default + opt-in live" 패턴의 1 추가 적용(현재: 0011 합성, 0012 합성 judge, 0013 관측, 0017 메타데이터 추출, 0023 HyDE, 0027 LoRA, 0028 보안 screen, 0029 case proposer). reviewer는 동일 shape 8회 관찰 → additive-pluggable idiom이 프로젝트 default.
- `proposer.aggregate.json`이 committable → N=100 → 130 → 150 ... 성장이 git log 시계열(`make real-eval-history-render` 경유 ADR 0005 history 패턴 mirror).

**Costs**

- ADR 0005 allowlist에 파일 1 추가(`reports/proposed/proposer.aggregate.json`). `synthetic_judge.aggregate.json`(ADR 0012) + `external_baselines.json`(ADR 0009) 기존 예외 mirror.
- 2-stage human gate가 "yaml 직접 편집"보다 단계 많음. `make case-propose`가 최근 30일 ≥ 2 후보 case 있는 seed doc skip → 사용자가 동일 template 재검토 안 함으로 완화.
- live backend 머지 시(PR3) prompt-injection 표면 확장; ADR 0008 chunk-body sanitizer 재사용이 완화책이나 sync 유지할 callsite 1 추가.

**Constraints (불변)**

- ADR 0001 naive baseline golden(`tests/data/naive_baseline_top_k.json`) byte-identity. proposer는 `eval/real_config.local.yaml`(private)만 touch, `eval/config.yaml`(공공 합성)은 절대 안 함.
- ADR 0003 답변 계약. proposer는 `run_rag_query` upstream; eval *입력* 생산, answer 출력 아님.
- ADR 0004 결정적 검증기. 공공 CI는 proposer 절대 invoke 안 함(`pr-eval.yml` 또는 `make smoke`에 `make case-propose` 없음).
- ADR 0005 aggregate-only commit 경계. case body는 `reports/proposed/*.local.yaml` gitignore 잔류; 메트릭 aggregate만 통과.
- ADR 0008 근거 경계. PR3 live backend는 `scripts/llm_judge.py`와 동일 sanitizer로 chunk 통과.

## 검토한 대안

- **proposer skip; 사람이 case 더 라벨링.** 기각: 5-15분/case 라벨링이 실제 N을 ~100 cap — 하루 노력도 ~30 case 추가만, 한계 case가 최저 가치(가장 novel한 실패 모드는 이미 catch). proposer의 1-3분/case 검토 경제가 N=200+ 현실화.
- **case auto-생성 + human gate skip.** 기각: ADR 0006이 real-data 표면에 LLM-as-second-opinion 원칙 pin. LLM이 질문 *+* 기대 label *둘 다* 생산 허용은 eval set이 스스로 grade — ADR 0006이 정확히 막으려는 실패 모드.
- **proposer를 공공 합성 표면에 사용.** 기각: 합성 case는 by construction crisply 구분(ADR 0006 §Alternatives); 거기 한계 case는 near-zero 가치. 라벨링 bottleneck은 real-data 한정.
- **`eval/synthetic_judge.py`를 case proposer로도 재사용.** 기각: 어느 한 표면 변경의 blast radius 배가. 두 script가 ~50줄 backend dispatch 공유; 3번째 LLM 표면 등장 전까지(그때 `eval/llm_backend.py` 추출) 중복이 더 저렴.
- **과거 hand-labeled case에서 결정적 proposer 훈련.** 시기상조; `openai_compatible` backend `proposer_accept_rate`가 여러 prompt iteration 걸쳐 < 0.5 plateau면 재방문.
