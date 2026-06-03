# Rationality judge — stub vs LLM (Sonnet 4.6) discriminating power

- Date: 2026-05-23
- Issue/PR: #1377
- ADR: [0056](../adr/0056-rationality-judge-measurement-surface.md) (Measurement appendix — LLM backend)
- Surface: historical v1 비공개 real-100, n=221 (aggregate-only archive-only — ADR 0005)

> **Historical scope note.** 이 audit 은 2026-05-23 v1 `real100` judge 비교 기록이며,
> 현재 private eval claim 근거가 아니다. 새 작업·PR·claim 에서 rationality judge
> 성능이나 slice-sensitive 변별력을 주장하려면 별도 `real100_v2` aggregate evidence 를
> 먼저 생성·검증해야 한다.

## 무엇을 측정했나

ADR 0056 의 trajectory-rationality judge 는 첫 PR(#987/#1326)에서 deterministic `stub` backend(SHA-256(trace subset))로만 측정됐다. ADR 0056 Out-of-scope 가 LLM backend 실측정을 별 PR 로 예약. 본 측정은 **같은 synthesis-primary trace 셋**을 두 backend 로 채점해 변별력을 비교한다 — stub 이 분포 floor 일 뿐인지, LLM judge 가 품질-상관 신호를 추가하는지.

## 측정 환경

- Index: prebuilt `data/index/real100` (26376 chunks, `EMBEDDING_BACKEND=hashing` 오프라인 기본 경로).
- Primary run: `agentic_full_llm` (`prompt_profile=llm_synthesis`) + `BIDMATE_TRACE_FULL=1 BIDMATE_SYNTHESIS_BACKEND=stub`. synthesis 는 stub(템플릿 passthrough) — **judge 변별력 측정이 목표이지 synthesis 품질 측정이 아님**. synthesis 가 도는 154 케이스에서 `answer_reasoning` 측정 가능, 나머지는 abstention drop.
- stub backend: SHA-256(trace subset, axis, case_id) → uniform[0,1]. cross-platform byte-identical 분포 floor.
- LLM backend: `claude-sonnet-4-6` (Anthropic OpenAI-compat 엔드포인트, temp=0, `BIDMATE_JUDGE_RESPONSE_FORMAT=none`). 1 LLM call/case (3-axis 합본). 비용 ≈$1.5 (judge len//3 input estimate 251k tokens, output ~27k).

## 결과 — per-axis mean ± std, 95% CI, stub↔LLM Spearman ρ

| axis | stub mean | stub std | LLM mean | LLM std | LLM 95% CI | Spearman ρ | p | n |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| `planner_decomposition` | 0.493 | 0.288 | 0.507 | 0.194 | (0.482, 0.533) | −0.090 | 0.185 | 221 |
| `retrieval_recalls` | 0.515 | 0.285 | 0.468 | 0.240 | (0.437, 0.499) | −0.033 | 0.623 | 221 |
| `answer_reasoning` | 0.505 | 0.290 | 0.318 | 0.163 | (0.292, 0.344) | −0.012 | 0.883 | 151 |

세 축 모두 **Spearman ρ≈0** (|ρ|≤0.09, 전부 p>0.18): stub 점수는 LLM judge 의 품질 판단을 추적하지 않는다. stub std≈0.29 는 uniform[0,1] 의 분포 폭 그대로 — 신호 없는 floor. LLM std(0.16–0.24)가 더 좁은 것은 judge 가 일관된 판단을 내려 분포가 수렴함을 시사.

## 변별력 — LLM mean by slice (stub mean in parens, 설계상 flat)

| slice | n | planner_decomp | retrieval_recalls | answer_reasoning |
|---|---:|---:|---:|---:|
| abstention | 104 | 0.531 (0.521) | 0.494 (0.516) | 0.310 (0.500) |
| comparison | 1 | 0.650 (0.913) | 0.200 (0.650) | 0.350 (0.358) |
| follow_up | 4 | 0.225 (0.387) | 0.100 (0.569) | — |
| single_doc | 112 | 0.494 (0.467) | 0.461 (0.512) | 0.325 (0.511) |

- `follow_up` (n=4) 의 degenerate trajectory 를 LLM 은 planner 0.225 / retrieval 0.100 로 명확히 페널티 — stub 은 0.387 / 0.569 노이즈로 무차별.
- `answer_reasoning` 은 모든 slice 에서 LLM ≪ stub (~0.31–0.35 vs ~0.50) — LLM 이 stub synthesis(템플릿 완성문)의 evidence 일관성을 낮게 변별. stub 은 ~0.50 균일.

(comparison/follow_up 은 n 이 작아 방향성 only.)

## 판정

- **stub = 분포 floor (품질 proxy 아님) — 설계 의도 확증.** ρ≈0 가 stub 의 cross-platform 재현성을 깨지 않으면서도 trajectory 품질과 무상관임을 보인다.
- **LLM backend = quality-correlated, slice-sensitive, evidence-aware 변별력 추가.** ADR 0056 의 "다른 backend 와 변별력 비교용 floor" 라는 stub 설계가 실측으로 검증됨.

## Caveats

- single judge (Sonnet) / single seed → judge-variance 미추정. haiku↔sonnet 교차(robustness)는 별 follow-up.
- single run. `answer_reasoning`=0.318 은 *stub synthesis* 채점값이라 synthesis *품질* 지표가 아님 (judge 변별력 신호).
- 비결정적(LLM) → CI 게이트 baseline 아님; 본 리포트가 측정 record. committed 는 aggregate/per-slice 만 (per-case score + qid 는 `rationality.*.local.json` gitignored, ADR 0005).
