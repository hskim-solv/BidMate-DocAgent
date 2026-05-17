# 0030: 리더보드 headline에 `naive_baseline`과 함께 `agentic_full` 포함

- **Status**: accepted
- **Date**: 2026-05-13
- **Deciders**: maintainer (hskim-solv)
- **Related**: issue #476, PR (forthcoming); ADR 0001(기준선 보존) + ADR 0024(agentic_full LLM as API default) 강화

## TL;DR

- `reports/leaderboard.md`는 snapshot당 단일 primary run(현재 `naive_baseline`, ADR 0001로 bit-deterministic flat)만 노출 → agentic-pipeline merge(HyDE/LangGraph/보안 screen 등)가 headline에 invisible.
- `agentic_full`을 평행 시계열로 추가 — `ablation_full` 신규 top-level key + sub-key whitelist + 동일 `defense-in-depth` 패턴(ADR 0012 mirror).
- forward-only 마이그레이션: 기존 21 snapshot은 `—`; backfill은 follow-up.

## 배경

`reports/leaderboard.md` + `docs/eval/leaderboard.md`는 `main` 커밋 걸친 headline 메트릭 시계열 차트. `scripts/leaderboard.py:67-98` 렌더러가 `reports/history/*.aggregate.json` 읽어 snapshot당 단일 메트릭 집합 표면화.

By construction(`scripts/write_synthetic_history.py:42`) 각 snapshot은 **primary run**만 운반 — 현재 `naive_baseline`(`eval/config.yaml` L4). ADR 0001이 `naive_baseline`을 분석 변형 floor로 의도 보존 + `hashing` backend에서 메트릭 bit-deterministic. 최근 main 5 커밋(`bb494…a7006`)이 동일 headline 값 렌더링 — ADR 0001이 보장하는 정확한 속성.

부작용: agentic-pipeline 변경(HyDE 확장 `#396`, LangGraph stage 2 `#458`, 보안 screen `#456`, cross-encoder reranker 골격 등)이 모두 `agentic_full`은 움직이지만 `naive_baseline`은 무변경 → 의미 있는 작업 머지되어도 리더보드 headline이 static 보임. `agentic_full` 결과는 `eval_summary.json::ablation.runs[]` 내부 거주하나 history-snapshot 경계 통과 안 함 → 리더보드 안 보임. *가시성* 갭, 측정 갭 아님.

## 결정

합성 리더보드 headline을 **2 파이프라인** 평행 시계열로 확장: `naive_baseline`(불변, ADR 0001 표면) + `agentic_full`(`full` 분석 변형 run).

메커니즘:

1. `scripts/run_real_eval_delta.SAFE_TOPLEVEL_KEYS`가 신규 top-level key `ablation_full` 수용. aggregate extractor가 sub-key(scalar 메트릭 + bootstrap CI sub-block) 명시 whitelist + case-level 거부 — `judge_ragas`(ADR 0012) + `retry_effectiveness`(#120)와 동일 defense-in-depth 패턴.
2. `scripts/write_synthetic_history.py`가 `eval_summary.json::ablation.runs[]`에서 `name == "full"` 엔트리 pull → 동일 whitelist 통과 → history snapshot에 `ablation_full`로 write.
3. `scripts/leaderboard.py`가 snapshot당 `ablation_full` 읽어 `reports/leaderboard.md`의 기존 `## Pipeline: naive_baseline` 표 아래 2번째 표(`## Pipeline: agentic_full`) 렌더링. Chart.js 페이지는 메트릭별 양쪽을 overlaid line series로 렌더.

**Forward-only 마이그레이션.** 기존 21 history snapshot은 `ablation_full` key 없음. 렌더러는 부재 값을 `—`로 처리 + chart에서 series 세그먼트 생략. backfill은 별도 concern(follow-up issue 보류), load-bearing 아님 — 신규 daily snapshot 누적으로 리더보드 자연 채움.

**Knob.** 향후 maintainer가 다른 2번째 파이프라인(예: `agentic_full_finetuned`) 원하면 변경은 `scripts/write_synthetic_history.py` 상수 1개(추출할 분석 변형 `name`) + `scripts/leaderboard.py` 렌더링 label. 본 ADR은 `full`을 명시 선택 — primary "production" 표면(ADR 0024) + matrix에서 가장 stable한 분석 변형.

## 결과

**Wins:**

- agentic-pipeline merge가 리더보드 headline에 하루 내 가시화(cron 주기, ADR 0029-인접 issue #471).
- 2-파이프라인 패턴이 ADR 0001 강화: 기준선이 활발 움직이는 `full` series 옆에서 *의도적* flat — apparent stagnation 아닌 의도된 story.
- Portfolio: 명시 "stable baseline + moving agentic" framing이 rigor(#0001) + progress(#0024) 축을 동시 표면화.

**Costs / locks-in:**

- `SAFE_TOPLEVEL_KEYS`에 엔트리 1 추가. `ablation_full` 향후 schema drift는 sub-key whitelist 갱신 필요(`judge_ragas`와 동일 유지보수 패턴).
- `reports/leaderboard.md` width / row 수 증가. CI gate `scripts/leaderboard.py --check`가 렌더링을 계약으로 계속 pin.
- Chart.js 페이지가 메트릭당 2 series 수용 필요. legend + tooltip 갱신.
- pre-#476 snapshot backfill은 opt-in; 리더보드 chart가 backfill 없으면 ~21일간 `agentic_full`을 partial series로 표시.

**Locked in:**

- `ablation_full` key 이름 + sub-key whitelist가 aggregate schema 계약 일부. rename은 deprecation cycle 또는 별도 ADR 필요.
- 리더보드 headline에서 `naive_baseline` + `agentic_full` 페어링(구체적 — "임의 분석 변형" 아님). 3번째 파이프라인(예: ADR 0027의 `agentic_full_finetuned`) 추가는 ADR 또는 본 ADR 수정 필요.

## 검토한 대안

- **기존 단일 표를 추가 칼럼으로 확장**(`baseline_acc`, `full_acc`, …). 표 더 넓고 스캔 어려움 + chart-렌더링 경로는 어차피 평행 series 필요. 가독성 사유 기각.
- **primary run을 `naive_baseline` → `agentic_full`로 교체.** ADR 0001 의도적 기준선 보존 invariant tear up; 기준선 회귀가 headline에 invisible. 즉시 기각 — ADR 0001이 load-bearing 제약.
- **별도 `reports/leaderboard_full.md` 파일 + 2번째 Jekyll 페이지.** side-by-side 2 series 원하는 story에 유지보수 표면 배가(CI check 2, 페이지 2, 렌더 함수 2). 응집성 사유 기각.
- **최신 `agentic_full` row만 렌더(single point, 시계열 아님).** 리더보드 핵심인 시계열 story 손실. 기각.
- **agentic story host용 별도 "decision log" 표면 대기.** real-data eval은 이미 `docs/real-data/private-100-doc-experiments.md` 존재; 합성 리더보드가 공공 표면 → 자체 equivalent 필요. 기각.
