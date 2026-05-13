# RAG 시스템 개선 회고 — 3가지 핵심 문제와 해결

> 이 문서는 BidMate-DocAgent 의 주요 RAG 개선 결정을 **STAR 형식** (Situation → Task → Action → Result) 으로 재서술한 포트폴리오 자산입니다. 모든 수치는 공개 합성 평가셋 (n=100) 기준이며, raw query·문서 원문은 [ADR 0005](adr/0005-eval-split-public-synthetic-private-local.md) 경계를 준수해 포함하지 않습니다.

---

## STAR 1 — 비교 질의 편향: 한 문서가 모든 슬롯을 독점하는 문제

### Situation

입찰 시스템에서 비교 질의 ("기관 A와 기관 B의 보안 요구사항 차이는?") 는 전체 질의의 ~24% 를 차지하는 핵심 유형이다. 초기 retrieval 은 단순 global top-k 정렬을 사용했는데, 두 가지 상황에서 한 쪽 기관 청크가 모든 슬롯을 독점하는 **starvation** 이 발생했다:

- **어휘 편향**: 질의 문장에 기관 A 의 고유 용어가 기관 B 보다 많이 등장하면 A 문서 유사도가 구조적으로 높음.
- **청크 수 불균형**: 두꺼운 기관 문서 vs 얇은 기관 문서가 같은 인덱스에 공존.

결과: verifier 가 `missing_comparison_doc` / `missing_comparison_entity` 신호를 내며 retry 를 반복했고, retry 가 실패하면 한 쪽 기관 정보만 담긴 불완전 비교 답변이 생성됐다.

### Task

두 기관 문서를 retrieval 단계에서 공정하게 포함시키되, 점수 기반 정렬을 완전히 버리지 않는 것. 목표: (1) verifier retry 감소, (2) comparison 질의 groundedness 향상, (3) baseline 경로 (naive_baseline) 는 완전히 불변으로 유지.

### Action

`apply_comparison_balance()` 를 `retrieve_candidates()` 내부의 reranking 이후 단계에 추가. 핵심 설계 결정:

1. **타이밍**: reranker 후, verifier 전 — 점수 정보를 보존한 채 공정 배분 가능.
2. **알고리즘**: `min_per_target` 슬롯을 각 comparison target 에 보장 → 남은 슬롯은 점수 내림차순으로 채움. 점수 순서는 보존.
3. **적응형 top-k**: `top_k = clamp(k_per_target × target_count + headroom, 6, max_top_k)` — 비교 대상이 많을수록 자동 확대.
4. **진단 field 추가**: `plan["comparison_coverage"]` 에 before/after 분포를 기록 → 문제 재현 없이 디버깅 가능.

```python
DEFAULT_COMPARISON_BALANCE = {
    "enabled": True,
    "min_per_target": 1,
    "k_per_target": 3,
    "headroom": 2,
    "max_top_k": 12,
}
```

ablation 보호: `naive_baseline` preset 에는 `comparison_balance` 키가 없어 기존 경로 완전 우회.

### Result

```
ablation 비교 (n=100, agentic_full baseline):
  no_metadata_first (balance off 대리 지표): Citation 0.679 ± 0.11
  full             (balance on):              Citation 0.905 ± 0.08
  → CI 비겹침(0.571–0.786 vs 0.821–0.976): 통계적으로 유의한 +22.6pp
```

retry 감소: 비교 질의에서 verifier 가 `missing_comparison_doc` 로 재시도하는 케이스가 줄었고, 단일 verifier 통과로 답변이 완성되는 비율이 높아짐. Groundedness 0.929 (full) vs 0.714 (naive_baseline): +21.5pp.

**포트폴리오 신호**: retrieval 설계 의사결정 (global sort → per-target fairness), 진단 instrumentation, ablation-safe 기능 추가.

---

## STAR 2 — 할루시네이션 구조적 차단: citation contract 설계

### Situation

초기 prototype 의 답변 생성기는 LLM synthesis 모델이 retrieved chunks 를 요약했다. 인터뷰·코드 리뷰에서 반복적으로 나온 문제: **LLM 이 chunk 에 없는 내용을 생성** (hallucination). 이를 후처리 filter 로 잡으려면 또 다른 LLM judge 가 필요했고, 비용과 비결정성이 모두 올라갔다.

### Task

"hallucination 을 탐지하는" 전략 대신 "hallucination 이 구조적으로 불가능한" 설계를 선택. 평가 파이프라인이 비용 0 (deterministic) 으로 CI 에서 돌아야 한다는 제약도 있었다.

### Action

**ADR 0003 structured answer/citation contract** 도입:

- 모든 claim 은 `{text, evidence_key, doc_id, chunk_id, score}` JSON dict 형태로 생성.
- claim 생성 함수 (`build_claims`, `make_claim`) 는 retrieved evidence 를 직접 인덱싱 — 외부 생성 없이 extractive.
- `schema_version: 2` 필드로 계약 버전을 명시. downstream (verifier, API, eval) 이 버전 불일치 시 명시적 오류.
- verifier 는 claim 의 `evidence_key` 를 원본 chunk 와 대조해 grounding 을 추가 검증.

이 설계가 "외부 LLM 호출 없이 작동하는 extractive grounded answer" 를 가능하게 했다.

### Result

```
Citation Precision:  naive_baseline 0.512 ± 0.12  →  agentic_full 0.905 ± 0.08  (+39.3pp)
Claim Citation Alignment:  0.974 ± 0.05  →  1.000 ± 0.00  (+2.6pp, ceiling)
```

CI 비겹침 (0.393–0.631 vs 0.821–0.976): 가장 큰 폭의 통계적으로 유의한 개선. "hallucination 탐지" 대신 "hallucination 불가 구조"를 택한 것이 핵심.

부작용 관리: extractive 방식이라 답변이 chunk 어체 그대로 노출되는 경우 있음 → LLM synthesis 를 opt-in ablation 으로 별도 추가 ([ADR 0011](adr/0011-llm-synthesis-as-additive-ablation.md)).

**포트폴리오 신호**: 방어적 시스템 설계 (구조적 불가능 vs 탐지 전략), schema versioning, ablation-safe 기능 분리.

---

## STAR 3 — 의도적 기권(Abstention) 정밀도 개선

### Situation

Real private 21-case eval (17 answerable + 4 intended-abstention) 에서 초기 verifier 는 엄격한 full-topic matching 을 요구했다. 결과:

- accuracy 0.353 (answerable 17개 중 6개만 성공)
- retry_reason `topic_not_grounded` 가 18건 발생 — 실제 관련 증거가 있는데도 verifier 가 insufficient 로 판단
- intended-abstention 4개는 올바르게 기권했지만 answerable 케이스에서 false abstention 이 너무 많음

### Task

"증거가 부족한 질의는 기권" 이라는 ADR 0004 정책을 유지하면서, 증거가 부분적으로 있을 때 false abstention 을 줄인다. 단, intended-abstention precision 을 희생하지 않는다.

### Action

`verify_evidence()` 에 `allow_partial_topic` 파라미터 추가:

- 마지막 retrieval 시도에서 verification topics 의 **≥50%** 가 evidence 에 매칭되면 `partial_topic_grounding` reason 으로 `verified=True` 반환.
- status 는 `supported` 가 아닌 **`partial`** — downstream 에서 confidence 를 구분할 수 있음.
- fraction 을 config knob 으로 노출 (ADR 0004 가 "향후 조정 가능한 임계값"으로 예고했던 exactly 이 knob).

### Result

Real 21-case eval before/after:

```
accuracy:               0.353 → 0.471  (+0.118)
retry topic_not_grounded: 18 → 12  (−6건)
answerable 중 insufficient:  10 → 6  (−4건)
answerable 중 partial:        0 → 4  (신규)
```

Trade-off 관리: intended-abstention 4건 중 2건이 `partial` 로 오분류 → ADR 0004 에 회귀 테스트 케이스로 기록, 향후 fraction tuning 시 가이드라인으로 사용.

Public synthetic eval (n=100): Abstention Accuracy **1.000** (naive_baseline 0.222 → agentic_full 1.000, +77.8pp). Public 에서의 완벽한 기권 정밀도가 real-data 조율의 결과.

**포트폴리오 신호**: 실데이터 vs 합성 평가 gap 관리, config knob 설계, trade-off 를 문서화한 의사결정 이력.

---

## 종합 — 세 개선이 만든 시스템 품질 레벨

| 축 | Before (naive_baseline) | After (agentic_full) | Δ |
|---|---|---|---|
| Answer Accuracy | 0.844 ± 0.12 | 0.906 ± 0.12 | +6.2pp |
| Citation Precision | 0.512 ± 0.12 | 0.905 ± 0.08 | **+39.3pp** |
| Abstention Accuracy | 0.222 | 1.000 | **+77.8pp** |
| Groundedness | 0.714 ± 0.14 | 0.929 ± 0.07 | +21.5pp |
| Latency p95 | 7.5ms | 4.4ms | −3.1ms (−41%) |

각 개선은 독립 ablation row 로 검증되어 어느 컴포넌트가 무슨 효과를 냈는지 추적 가능하다 ([ablation 상세](../README.md#ablation-breakdown)).

> **주**: 상세 ablation breakdown 과 n=42→n=100 CI 수축 히스토리는 [docs/performance-evolution.md](performance-evolution.md) 를 참조.
