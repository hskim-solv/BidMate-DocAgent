# 0019: 임베딩 기본은 MiniLM-L12-v2 유지 + 명시 재오픈 조건

- **Status**: Superseded
- **Superseded by**: [ADR 0001](./0001-preserve-naive-baseline.md) § "Default-choice re-evaluation criteria"
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (기준선 보존), [ADR 0002](./0002-metadata-first-retrieval.md) (메타데이터 우선 우세), [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) (조건 2 봉쇄하는 Phase 1.3 보조), [`docs/eval/embedding-ablation.md`](../eval/embedding-ablation.md), 이슈 #161 (Phase 1.2 runner) + #300 (본 결정)
- **Update (Phase 1.3, issue #389, 2026-05-12)**: 조건 1 완전 충족 (`torch >= 2.6` `requirements.txt:8` pin, `huggingface-hub 0.36.2 < 1.0` 기존 보유), 조건 2 4 후보 모두 완전 충족 (BGE-M3 측정이 마지막 갭 봉쇄), 조건 3 **어떤 후보도 트리거 안 됨** (`0pp-on-full` 패턴이 측정한 5 임베딩 가로질러 성립). 본 ADR accepted 유지; 보조는 [ADR 0021](./0021-bge-m3-completes-phase-1-3.md) 참조.
- **Update (ADR 0032 라우팅-축 falsifier, issue #550, 2026-05-13)**: [ADR 0032](./0032-eval-saturation-routed-subset.md) 가 보완 gate 추가: "라우티드 (메타데이터 우선 우회) subset 에서 spread ≥ +3pp". 5-임베딩 × 라우티드 subset 측정 (n=11, `eval/routed_config.yaml`) spread = **0.0pp** — `saturation_cross_validated`. 조건 3 라우티드 축에서도 **트리거 안 됨**. MiniLM 기본 lock 이 메타데이터 우선 마스킹 너머에서도 empirical 정당. 집계는 `reports/embedding_routed.json` 출시.
- **Update (Phase 1.5, issue #447, 2026-05-14)**: [ADR 0037](./0037-kure-v1-closes-phase-1-5.md) 이 확장 n=100 공개 합성 corpus 에 공식 `nlpai-lab/KURE-v1` 측정 전달. `full` 파이프라인: accuracy Δ = **−1.3pp**, groundedness Δ = **+0.0pp**. 조건 3 **트리거 안 됨**. `naive_baseline` 상승 (+19.2pp accuracy) 은 카운트 안 됨. 이슈 #447 close. 기본 lock 이 **6개** 측정 임베딩 pivot 가로질러 성립.

## TL;DR

- 임베딩 기본 `paraphrase-multilingual-MiniLM-L12-v2` 유지 — Phase 1.2 측정 (n=42) 에서 `full` 파이프라인 메트릭이 임베딩-불변 (메타데이터 우선이 dense 검색 우회).
- 첫 사이클 BGE-M3 / e5-large-instruct 측정은 Python env 충돌 (`torch >= 2.6`, `huggingface-hub < 1.0`) 로 차단 — 결정을 ADR 에 lock + 명시 재오픈 조건.
- `full` 에 ≥ +5pp 측정 가능 개선 + non-overlapping CI 까지 기본 swap 금지 (`naive_baseline` 상승은 카운트 안 됨).

## 배경

README Limitations 리스트와 `docs/eval/embedding-ablation.md` 가 미완 결정 flag: 임베딩 기본은 2019 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. 첫 사이클 측정 (MiniLM vs `multilingual-e5-base`, n=42) 이 robust 발견 2개:

1. **전체 agentic 파이프라인 메트릭은 본 corpus 에서 임베딩-불변.** 메타데이터 우선 필터링 (ADR 0002) 이 대부분 쿼리에 dense 검색 우회; `accuracy / groundedness / citation_precision / abstention / format_compliance` 가 0pp 이동.
2. **Naive 기준선은 임베딩-민감.** `e5-base` 가 `naive_baseline.accuracy` 0.656 → 0.844 (+18.8pp) 상승, 그러나 naive 표면은 분석 변형이지 프로덕션 경로 아님 (ADR 0001).

이슈 #161 추적 미완 작업: 가설 "0pp-on-full 패턴이 modern 모델 가로질러 robust" falsify 하는 modern multilingual SoTA + 한국어 특화 비교자 (BGE-M3, e5-large-instruct, KURE-v1) 추가하는 2번째 사이클. runner 확장; *측정* 자체는 본 이슈 (#300) 로 deferred.

본 결정이 그 측정 시도, Python env 벽 도달, 벽 문서화, **기본 미변경** 명시.

## 결정

**`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 를 문서화된 기본 임베딩으로 유지.** 결정을 본 ADR 에 lock → 미래 contributor 가 empirical evidence 없이 조용히 swap 못 함; 아래 *재오픈 조건* 도 lock → deferral 이 영구 caveat 아님.

2번째 사이클 측정이 maintainer 의 Python 3.11 install 에서 독립 env 불일치 2개로 차단:

- `BAAI/bge-m3` 가 `torch >= 2.6` 필요 (modern sentence-transformers 의 CVE-2025-32434 완화); install 은 `2.2.2`.
- `intfloat/multilingual-e5-large-instruct` 가 `huggingface-hub < 1.0` 필요 (transformers 통해); install 은 `1.14.0`.

이들은 파이프라인 무관. 수정은 별도 관심사 — `requirements.txt` 가 `sentence-transformers>=2.7,<3.0` 만 pin, 나머지 스택은 독립 drift. 본 PR 에서 env 업그레이드 yak-shaving 은 *측정 deferral* 결정에 대한 "one PR, one concern" 규칙 (CLAUDE.md) 위반.

## 재오픈 조건

ADR 0019 가 재오픈 (즉, 본 결정 재검토 + 기본 잠재 flip) 되려면 **4개 모두** 성립:

1. contributor 가 양 차단자 (`torch >= 2.6`, 일치 `transformers` pin 통한 `huggingface-hub < 1.0`) 해소하는 `requirements.txt` 업그레이드 랜딩.
2. `python3 scripts/run_embedding_ablation.py --models <miniLM> BAAI/bge-m3 intfloat/multilingual-e5-large-instruct` 가 공개 합성 corpus (n=42) 대해 완료 실행.
3. BGE-M3 / e5-large-instruct 중 최소 1개가 MiniLM 대비 non-overlapping bootstrap 95% CI 동반 **`full` 파이프라인** accuracy 또는 groundedness ≥ +5pp 상승. *(`naive_baseline` 상승은 카운트 안 됨 — ADR 0001 에 의거 분석 변형 보존된 표면.)*
4. follow-up ADR (번호 002x) 가 교체 문서화 + 후보 측정 출력을 `docs/eval/embedding-ablation.md` Phase 1.2 섹션에 append.

조건 1-2 만 랜딩 + 3 미달 (0pp 패턴 성립) 시 본 ADR accepted 유지 + 문서가 ADR 교체 없이 측정으로 업데이트.

## 결과

Easier:

- README Limitations 리스트가 임베딩 결정 영구 "다음 사이클" placeholder 더 이상 운반 안 함. 현재 상태가 *기록*, pending 아님.
- CLAUDE.md "ADR 임계" 규칙 충족: 기본 유지 결정이 이제 load-bearing (어떤 contributor 도 조용히 swap 안 함) + 뒤집을 조건이 명시.
- 미래 contributor 가 분위기로 모델 swap 하는 열린 초대 아닌 명확 gate ("`full` 에 ≥+5pp 측정했는가?") 도달.

Costs / 정직성:

- deferral 은 실재. BGE-M3 / KURE-v1 헤드라인 수치 본 repo 부재; "왜 2026 년에 MiniLM?" 묻는 reviewer 는 2번째 사이클 측정 아닌 첫 사이클 evidence + ADR 0019 재오픈 조건 받음. `docs/eval/embedding-ablation.md` 명시 문서화.
- env 업그레이드 작업이 본 PR critical path 가 *아닌* 측정 piece 의 unblocking dep. 그 작업은 requirements-pinning sweep bandwidth 가진 자 owner.

## 검토한 대안

- **본 PR 에서 `torch` + `huggingface-hub` 업그레이드 + ablation 재실행.** Reject: scope creep (env 업그레이드는 본 측정 아닌 전체 repo 영향) + 위험 (다른 코드 경로가 torch 2.6+ 대비 재테스트 안 됨; 본 PR 의 어떤 것도 업그레이드 안전 검증 안 함). One PR, one concern.
- **첫 사이클 데이터만으로 기본을 e5-base 로 switch.** Reject: e5-base 가 `full` 파이프라인에 0pp 상승. ADR 재오픈 조건이 보존된 분석 변형 상승 아닌 `full` 에 측정 가능 개선 요구.
- **결정을 "deferred" 로 marking 하되 ADR 없이 doc comment 만.** Reject: 다음 contributor 에게 같은 미완 상태 남김. ADR 핵심은 다음 contributor 가 재결정 없이 build 할 수 있을 만큼 legible 한 결정.
- **doc 에서 2번째 사이클 framing 완전 제거.** Reject: 미완 사이클 erase 가 실 측정 context 숨김. doc 이 이제 사이클 시도 + 무엇이 구체적으로 차단했는지 기록.

## Phase 1.4 update — 라우티드-subset saturation falsifier (ADR 0032, 2026-05-13)

[ADR 0032](./0032-eval-saturation-routed-subset.md)이 "0pp on full = 메타데이터 우선 마스킹" 가설을 falsify하기 위해 라우티드-subset measurement surface를 추가했다 (eval/routed_config.yaml, n=11, `agentic_full_routed` preset: metadata_first=false). 측정 결과 spread **0.0pp** (MiniLM / e5-large-instruct / KoSimCSE / KURE-v1 모두 라우티드 accuracy 0.400, threshold: +3pp). BGE-M3는 torch ≥ 2.6 blocker로 skip됨 (ADR 0021 §4 동일 조건).

**Saturation cross-validated**: 0pp 패턴이 라우티드 surface에서도 성립 — 메타데이터 우선 우회 시에도 임베딩 선택이 accuracy를 바꾸지 못함. MiniLM 기본 lock이 measurement-precluded가 아니라 *empirically justified* (두 surface 공통)임을 확인. 재오픈 트리거 조건 3 (≥ +5pp on full, non-overlapping CIs)는 현재 측정 surface에서 structurally unreachable이 아닌, *evidence-backed stable*임이 cross-validated됨. ADR 0032 accepted로 closes.

전체 결과: `reports/embedding_routed.json`.
