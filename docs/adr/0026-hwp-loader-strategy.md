# 0026: `HwpNativeLoader` 전략 결정 — deprecate / promote / integrate / keep

- **Status**: proposed
- **Date**: 2026-05-12
- **Deciders**: hskim-solv
- **Related**: issues [#167](https://github.com/hskim-solv/BidMate-DocAgent/issues/167) (spike origin), [#231](https://github.com/hskim-solv/BidMate-DocAgent/issues/231) (측정), [#363](https://github.com/hskim-solv/BidMate-DocAgent/issues/363) (observability), [#365](https://github.com/hskim-solv/BidMate-DocAgent/issues/365) (this decision); ADR [0001](0001-preserve-naive-baseline.md) (baseline invariant), ADR [0011](0011-llm-synthesis-as-additive-ablation.md) (additive-LLM pattern — precedent for opt-in spikes).

## Context

`HwpNativeLoader` ([`ingestion.py:111-192`](../../ingestion.py)) is opt-in spike scaffolding from [#167](https://github.com/hskim-solv/BidMate-DocAgent/issues/167). Activated only when `BIDMATE_HWP_LOADER=native`, it parses the binary natively via `pyhwp.Hwp5File` and falls back to the CSV `텍스트` baseline (ADR 0001) on any `ImportError` / `OSError` / `RuntimeError`. The default loader stays `HwpCsvTextLoader`; the baseline contract is preserved regardless of this decision.

[#363](https://github.com/hskim-solv/BidMate-DocAgent/issues/363) (landed in [`1b63c81`](https://github.com/hskim-solv/BidMate-DocAgent/commit/1b63c81)) added observability — `last_fallback_reason` field and a `RuntimeWarning` emission on every silent CSV-fallback — so the spike's failure rate is now measurable from real-eval logs. [#231](https://github.com/hskim-solv/BidMate-DocAgent/issues/231) (PR [#425](https://github.com/hskim-solv/BidMate-DocAgent/pull/425)) ran a parallel measurement: native CLI extraction (`hwp5txt`) vs `libreoffice → visual_ingestion` v2 (table-aware path). Result summary from [docs/hwp-extraction-comparison.md:145-187](../hwp-extraction-comparison.md) (N=15):

| | hwp5txt | libreoffice → visual-v2 |
|---|---|---|
| 성공률 | 15 / 15 | 0 / 15 (`pdf_not_produced`) |
| Median char | 24,085 (p95 33,096) | — |
| Median latency | 4,645 ms (p95 18,277) | — |
| 인코딩 오류 | 0 / 15 | — |
| 표 재구성 | 0 (구조 손실) | — (path B 실패) |

The Pre-Phase-3 audit flagged "scaffold that became load-bearing" as a 6-month pain item. The question this ADR resolves: **does the spike stay as-is, get promoted, get folded into `visual_ingestion` v2, or get removed?**

<!-- TODO(author): 위 3 단락 외의 "왜 지금 결정하는가" 문맥이 있다면 한 단락 추가.
     예) Phase 3 visual_ingestion v2 로드맵의 의존성, Korean RFP 코퍼스의 HWP 비율 등. -->

## Decision

<!-- TODO(author): 한 문장으로 채택할 옵션을 명시. 예:
     "We deprecate `HwpNativeLoader` and remove the `BIDMATE_HWP_LOADER=native` env-var branch."
     "We integrate `HwpNativeLoader` into `visual_ingestion` v2 as the canonical HWP code path."

     그 다음 구체적으로 변경될 contract:
     - `BIDMATE_HWP_LOADER` env var 의 새 동작 (제거 / 기본값 변경 / 새 값 추가)
     - `requirements.txt` 변경 (pyhwp 추가 / 유지 / 제거)
     - `make_hwp_fallback_document` (visual_ingestion.py:750-806) 의 운명 (보존 / 통합 / 폐기)
     - 후속 구현 이슈 번호 -->

_(채택할 옵션 + 후속 구현이 변경할 contract 를 author 가 기록.)_

## Consequences

<!-- TODO(author): 채택된 옵션이 야기하는 결과를 wins / costs / locked-in 로 정리. -->

**Wins**

<!-- 예 (option 별):
     - deprecate: spike 코드 약 80 라인 제거; 가짜 ingestion 분기 사라짐; observability noise 감소.
     - promote: HWP 본문 추출 품질이 default 로 올라감; CSV preprocessing 의존성 제거 가능.
     - integrate: HWP 처리가 단일 코드 경로 (visual_v2) 에 통합; 분기 surface 감소.
     - keep: 결정 비용 0; 다음 실측 cycle 후 재평가 여지. -->

**Costs**

<!-- 예 (option 별):
     - deprecate: native HWP 표 데이터 손실; pyhwp 사용자 regression.
     - promote: pyhwp 가 사실상 required dependency 가 됨; CI / requirements.txt impact.
     - integrate: ingestion.py + visual_ingestion.py 양쪽에 걸친 refactor cost.
     - keep: "load-bearing scaffold" 위험이 6 개월 더 누적. -->

**Locked-in contracts**

- ADR [0001](0001-preserve-naive-baseline.md) baseline invariant: 어떤 옵션을 택해도 `HwpCsvTextLoader` 가 default 로 유지되며 CSV `텍스트` fallback 경로는 bit-identical 로 보존된다. native 작업은 모두 additive — replacement 가 아니다.
- ADR [0003](0003-structured-answer-citation-contract.md) answer-contract: HWP 본문 출처 metadata 의 schema 변경 시 `schema_version` bump 필요.

## Alternatives considered

The four options from [#365](https://github.com/hskim-solv/BidMate-DocAgent/issues/365) are inventoried below. 채택된 옵션은 위 **Decision** 에 기록되고, 비채택 옵션은 아래 "왜 아닌가" 줄을 채워 남긴다.

1. **Deprecate** — `HwpNativeLoader`, `_extract_hwp_native`, `BIDMATE_HWP_LOADER=native` 분기 제거.
   - 명시된 비용: native HWP 표 구조 추출 능력 상실 + pyhwp 의존 사용자 regression.
   - 명시된 이익: load-bearing surface 축소; spike 1 개 제거.
   - <!-- TODO(author): 채택 또는 비채택 사유 한 줄. #231 결과 표의 어떤 행이 근거? -->

2. **Promote to default** — pyhwp 설치 감지 시 native parsing 을 default 화.
   - 명시된 비용: pyhwp 가 사실상 required dep 화; CI / `requirements.txt` impact.
   - 명시된 이익: HWP fidelity 가 default 로 향상; Korean stack positioning 강화.
   - <!-- TODO(author): 채택 또는 비채택 사유 한 줄. #231 의 latency p95 = 18.3 s, 0% 인코딩 오류는 어떻게 평가? -->

3. **Integrate into `visual_ingestion` v2** — `make_hwp_fallback_document` ([visual_ingestion.py:750-806](../../visual_ingestion.py)) 와 native parser 를 같은 모듈에 통합; HWP 처리가 single ingestion seam.
   - 명시된 비용: `ingestion.py` + `visual_ingestion.py` 양쪽 refactor.
   - 명시된 이익: 단일 HWP 코드 경로; metadata schema 명료; visual-v2 trajectory 와 정렬.
   - <!-- TODO(author): 채택 또는 비채택 사유 한 줄. #231 의 Path B 실패 (libreoffice base install 에 HWP filter 부재) 는 visual_v2 통합 시점에 어떻게 다뤄지나? -->

4. **Keep + observe** — 현재 opt-in spike 유지; #363 의 observability 결과를 한 cycle 더 누적.
   - 명시된 비용: "scaffold became load-bearing" 위험 지속.
   - 명시된 이익: 결정 deferral; 다음 real-eval cycle 의 fallback rate 데이터로 보강.
   - <!-- TODO(author): 채택 또는 비채택 사유 한 줄. real-eval native fallback rate 가 미수집 (pyhwp Python pkg 미설치) 인 점은 변수인가? -->

## 미수집 측정 (참고)

[#365](https://github.com/hskim-solv/BidMate-DocAgent/issues/365) 가 명시한 결정 input 중 다음은 본 PR 시점에 미수집:

- **Real-eval native fallback rate.** `make real-eval` 을 `BIDMATE_HWP_LOADER=native` 로 1 cycle 돌려 per-doc `last_text_source` / `last_fallback_reason` 를 집계해야 한다. 본 PR 환경에는 pyhwp **CLI** (`hwp5txt`) 만 설치되어 있고 **Python 패키지** (`hwp5.xmlmodel.Hwp5File`) 가 부재하므로, native loader 가 `ImportError` 로 100% fallback 한다 — 측정 의미가 없다. 정확한 수집을 위해서는 사전에 `pip install pyhwp` 가 필요하며, 이는 본 ADR 의 follow-up 구현 PR 의 사전 단계로 다룬다.
- **Korean RFP 코퍼스 HWP 비율 정량.** `data/files/` 의 96 개 HWP / 전체 doc 수 비율은 단순 집계이지만 `data/data_list.csv` 와의 join 이 필요 — 별도 step.

이 두 항목 미수집은 본 ADR 의 status 를 `proposed` 로 유지하는 근거 중 하나이다. **Decision** 이 위 두 항목 없이도 결정 가능하다고 author 가 판단하면 그 사유를 위 **Decision** 단락에 명시.
