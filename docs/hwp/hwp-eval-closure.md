---
title: HWP Eval 갭 해소
layout: page
permalink: /hwp-eval-closure/
---

# HWP Eval 갭 해소 (ADR 0039)

이 문서는 2026년 5월에 공개 합성(synthetic) eval 표면과 private 100-doc
corpus(96% HWP) 사이에서 식별된 네 가지 갭, 그리고 이를 해소한 PR 스택을
기록한다.

## 배경(Background)

ADR 0036 (#641) 이 `HwpNativeLoader` 를 pyhwp-gated 기본값으로 출하한 후,
private corpus 는 96 HWP + 4 PDF
(`data/index/real100/ingestion_report.json`)였다.
세 가지 질문이 떠올랐다:

1. HWP 데이터가 공개 eval 에서 실제로 행사(exercise)되는가?
2. 공개 eval 질문이 real-data 품질을 변별하는가?
3. hard-case 평가(구조적 결함)가 가능한가?

코드 수준 점검에서 네 가지 갭을 발견했다:

| # | 갭 | Before | After |
|---|-----|--------|-------|
| 1 | 공개 synthetic eval에 HWP fixture 없음 | 100 cases, JSON corpus only | 105 cases (+5 HWP hardcase) |
| 2 | `eval_summary.json`에 `by_format` 없음 | HWP vs PDF 분리 불가 | `by_format.hwp` aggregate 추가 |
| 3 | HWP loader ablation preset 없음 | `naive_baseline` / `agentic_full`만 | `hwp_csv_text` / `hwp_native` / `hwp_native_tables` 3-way |
| 4 | 공개 hardcase에 구조 카테고리 없음 | retrieval/abstention 변별만 (22 cases) | +4 구조 카테고리 활성 (ADR 0039) |

## PR 스택 (ADR 0039 Kahn-ordered)

```
main
 └─ PR-0  ADR 0039 — HWP structural hardcase taxonomy (docs only)
     └─ PR-A  공개 synthetic HWP fixture 2개 + 5 eval cases
         └─ PR-B  eval_summary by_format aggregate + SAFE_FORMAT_BUCKET_KEYS
             └─ PR-C  hwp_csv_text / hwp_native / hwp_native_tables ablation preset
                 └─ PR-D  ADR 0039 rotated_or_skewed + ocr_noisy 카테고리 활성
                     └─ PR-E  leaderboard HWP slice (this PR)
```

| PR | Issue | Branch | 핵심 파일 |
|----|-------|--------|-----------|
| PR-0 | #646 | `docs/issue-646-adr-0039-hwp-hardcase` | `docs/adr/0039-hwp-structural-hardcase-taxonomy.md` |
| PR-A | #648 | `feat/issue-648-hwp-synthetic-fixture` | `data/raw/rfp_agency_f/g_hwp.json`, `eval/config.yaml` (+5 cases) |
| PR-B | #650 | `feat/issue-650-eval-by-format-breakdown` | `eval/run_eval.py`, `scripts/run_real_eval_delta.py`, `tests/test_eval_by_format_aggregate_regression.py` |
| PR-C | #652 | `feat/issue-652-hwp-loader-ablation` | `eval/config.yaml` (+3 ablation rows), `scripts/build_index.py` (`--hwp_loader`) |
| PR-D | #654 | `feat/issue-654-hwp-hardcase-tagging` | `eval/config.yaml` (tagging only) |
| PR-E | #657 | `feat/issue-657-leaderboard-hwp-surface` | `scripts/leaderboard.py`, `docs/hwp/hwp-eval-closure.md` (this file) |

## 각 갭 해소가 전달하는 것

### Gap 1: HWP fixture (PR-A)

`metadata.source_format: "hwp"` 를 가진 합성(synthetic) JSON fixture 2개:
- `rfp-agency-f-smart-factory-hwp` — table-heavy 예산 명세 (4억 3,500만원)
- `rfp-agency-g-traffic-hwp` — layout-broken 교통 관리 RFP (2억 8,000만원)

새 eval case 5개는 `single_doc`, `comparison`, `follow_up`, `abstention`
쿼리 유형을 다룬다. `.hwp` 바이너리는 커밋하지 않는다(저작권; ADR 0005
public/private 경계).

### Gap 2: by_format aggregate (PR-B)

`eval/run_eval.py:summarize_run` 은 이제 결과를 `metadata.source_format` 별로
묶는다. `eval_summary.json` 에 top-level `by_format` 키가 추가된다:

```json
{
  "by_format": {
    "hwp": { "num_predictions": 2, "accuracy": 0.85, ... },
    "synthetic_public_sample": { "num_predictions": 103, ... }
  }
}
```

`SAFE_FORMAT_BUCKET_KEYS = frozenset({"hwp", "pdf", "synthetic_public_sample"})`
는 `run_real_eval_delta.py` 의 fail-closed whitelist 다(ADR 0005 guard).

### Gap 3: Loader ablation preset (PR-C)

`eval/config.yaml:ablation_runs` 에 세 행(`hwp_csv_text`, `hwp_native`,
`hwp_native_tables`)이 추가되며, 모두 `pipeline: agentic_full` 위에
구축된다(ADR 0001 baseline invariant 보존). `scripts/build_index.py` 에
`--hwp_loader {csv,native,native_tables}` 가 추가되어 `ingestion.py` 의
`_resolve_loader` 가 실행되기 전에 `BIDMATE_HWP_LOADER` 를 설정한다.

### Gap 4: 구조적 hardcase 카테고리 (PR-D)

`eval/config.yaml` 에서 활성화된 ADR 0039 카테고리 4개:

| 카테고리 | 태깅된 Fixture case |
|----------|---------------------|
| `table_heavy` | hwp_f_table_budget |
| `layout_broken` | hwp_g_layout_contract_amount |
| `rotated_or_skewed` | hwp_g_layout_contract_amount, hwp_compare_fg_scale |
| `ocr_noisy` | hwp_g_layout_contract_amount, hwp_compare_fg_scale |

`eval/run_eval.py` 의 `by_hardcase_category` 는 어떤 카테고리 키든 자동으로
흡수한다 — 코드 변경 불필요.

## Leaderboard 가시성 (PR-E)

`scripts/leaderboard.py` 는 이제 다음을 렌더링한다:
- `reports/leaderboard.md` 에 세 번째 **HWP Slice** 표
  (`## HWP Slice: by_format[hwp]`)
- GitHub Pages leaderboard 의 각 headline metric chart 에 `hwp_format`
  Chart.js series(teal line)

과거 스냅샷은 ADR 0030 forward-only 정책에 따라 `—` 를 표시한다. `main` 의 새
CI 실행이 앞으로 series 를 채운다.

## Invariant 체크리스트

- [x] ADR 0001: `naive_baseline` preset 불변; 새 ablation 행은 additive
- [x] ADR 0005: 커밋된 aggregate 에 per-case payload 없음; `SAFE_FORMAT_BUCKET_KEYS` 는 fail-closed
- [x] ADR 0007: 모든 브랜치는 `<type>/issue-<N>[-<slug>]`; 모든 PR 에 `Closes #N`
- [x] ADR 0030: Leaderboard 는 forward-only; PR-B 이전 스냅샷은 HWP slice 에서 `—` 표시
- [x] ADR 0036: pyhwp-absent CI 안전 — fixture 는 JSON, `.hwp` 바이너리 미커밋
- [x] ADR 0039: PR-D 머지로 Status 가 proposed → accepted 로 승격
