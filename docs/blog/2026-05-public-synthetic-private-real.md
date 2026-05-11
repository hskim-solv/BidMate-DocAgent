---
layout: page
title: Public synthetic + Private real, 두 평가 surface
date: 2026-05-11
permalink: /blog/2026-05-public-synthetic-private-real/
---

> 결론: 재현 가능성과 honest signal은 하나의 평가 surface로 동시에 못 가진다.
> 두 surface를 *코드 강제 경계*(`.gitignore` + pre-commit hook + 스크립트 allowlist)로 유지해 둘 다 가진다.
> 이 결정의 정당성은 이슈 #69에서 *공개 평가가 회귀를 놓치고 실데이터가 잡은* 사례로 입증된다.

## 두 평가 surface가 필요한 이유

[ADR 0005](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0005-eval-split-public-synthetic-private-local.md)의 첫 문단이 딜레마를 단정한다.

> "The system has two evaluation needs that pull in opposite directions: **Public reproducibility** — anyone cloning the repo must be able to run a meaningful eval without secrets, paid APIs, or data we cannot redistribute. **Honest signal** — synthetic RFPs do not exercise the failure modes that show up on real procurement documents."

공개 평가 하나로 두 요구를 다 충족하려고 하면 둘 다 망한다. 합성 데이터는 분포가 깔끔해서 *진짜 실패 모드*를 자극하지 못하고, 실데이터를 공개하면 *재현 가능성*은 얻지만 발주기관/사업명/원문이 노출된다.

본 프로젝트의 결정: 두 surface를 *동시에* 유지하되, 각 surface의 *경계는 컨벤션이 아닌 코드*로 강제한다.

## 두 surface의 역할 구분

| Surface | 위치 | 역할 | 비고 |
|---|---|---|---|
| **Public synthetic** | `eval/config.yaml`, `data/raw/` | PR마다 자동 측정, README 성능표 source of truth | hashing embedding으로 offline 가능 |
| **Private local** | `eval/real_config.example.yaml` (scaffold), 실제 config + corpus는 gitignored | 실패 분류의 *진짜 원천*, `reports/real100/` aggregate만 commit | 로컬 측정 → 의사결정 → aggregate만 PR |

"파일별 판단"이 아니라 **`*.example.yaml` 컨벤션 + `.gitignore`** 라는 한 줄 규칙으로 surface가 정해진다.

## 세 층의 방어선: 코드 강제 경계

ADR은 *정책*이고 강제하는 것은 코드다. private 데이터가 실수로 commit되는 경로를 세 단계로 닫는다.

### 1. `.gitignore` — 파일 시스템 레벨 차단

```gitignore
# .gitignore (발췌)
data/files/                                # 원본 RFP 파일
data/data_list.csv                         # 메타데이터 + 본문 추출
eval/*.local.yaml                          # 실데이터 gold config
reports/*                                  # 모든 평가 출력
!reports/real100/baseline.aggregate.json   # 단, aggregate만 allowlist
!reports/real100/history/                  # baseline 변경 history
```

전부 차단하되 `reports/real100/baseline.aggregate.json`만 *명시적으로* 풀어준다. 즉 aggregate 외의 어떤 출력물도 git tree에 들어갈 수 없다. case_results, query text, doc_id, evidence는 디스크에 남지만 *repo에는 못 들어간다*.

### 2. `.githooks/pre-commit` — commit 단계의 보호망

```bash
# .githooks/pre-commit (발췌)
BLOCKED='data/files/|data/data_list\.csv|eval/.*\.local\.yaml|reports/real100/(?!baseline\.aggregate\.json|history/)'
if git diff --cached --name-only | grep -E "$BLOCKED"; then
  echo "❌ Blocked: see ADR 0005."
  exit 1
fi
```

`.gitignore`를 우회하는 (예: 의도적으로 `git add -f`) 시나리오를 commit 직전 차단. `--no-verify` 만이 의도적 우회의 *명시적 신호*가 된다. 머지된 코드에서 `.no-verify` 흔적을 보는 순간 리뷰어는 "왜 hook을 우회했지?"를 물을 수 있다.

### 3. `scripts/run_real_eval_delta.py` — 스키마 레벨 allowlist

PR에 aggregate를 첨부할 때조차 *스키마 드리프트로 누수*가 발생할 수 있다. 예를 들어 새 metric을 추가하다가 실수로 `top_failing_cases: [...]` 같은 필드가 끼면, 그 필드명에 case ID가 들어갈 수 있다.

```python
# scripts/run_real_eval_delta.py
SAFE_TOPLEVEL_KEYS = frozenset({
    "num_predictions", "accuracy", "groundedness",
    "citation_precision", "citation_grounding",
    "claim_citation_alignment", "answer_format_compliance",
    "abstention", "retry", "latency", "stage_latency",
    # case_results / query / doc_id / evidence 같은 per-case 키는 *허용 안 됨*
})
```

추출기가 *명시적 allowlist*로만 작동한다. 새 키가 들어와도 자동 통과하지 않으며, 의도된 metric이라면 allowlist 갱신이 PR diff로 보인다. 스키마 드리프트가 발생해도 private 누수는 *구조적으로* 불가능.

## 정당성 사례 — 이슈 #69 회귀

세 층의 방어선이 정당하려면 *그게 없었으면 일어났을 일*이 있어야 한다. 이슈 [#69](https://github.com/hskim-solv/BidMate-DocAgent/pull/88) 가 그 사례다.

**변경 내용.** verifier의 relaxed 단계에서 partial-topic grounding을 허용 (verification topics의 50% 이상 매칭 시 `verified=True`). 목적은 false abstention 감소.

**공개 평가가 본 것 (n=42, hashing backend).** accuracy 0.844 → 0.844, citation precision 0.512 → 0.512. **회귀 없음**으로 보임 → 머지 후보 ✅.

**실데이터가 본 것 (n=21, 17 answerable + 4 intended-abstention).** [실데이터 Decision Log](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/private-100-doc-experiments.md) aggregate:

| Metric | Before | After | Δ |
|---|---:|---:|---:|
| accuracy | 0.353 | 0.471 | **+0.118** ✅ |
| abstention (intended) | 1.000 | 0.500 | **−0.500** ⚠️ |

의도된 abstention 4건 중 **2건이 `insufficient` → `partial`로 잘못 분류**됐다. 즉, "out-of-corpus 질문인데 답이 있는 척" 하는 false positive가 절반 수준에서 발생.

**왜 공개 평가는 못 잡았는가?** 합성 abstention 케이스(예: `기관 A의 양자암호 적용 방안은?`)는 corpus와 *분명히* 분리된다. 실데이터에서는 사정이 다르다 — out-of-corpus 질의도 corpus 내 문서와 *부수적인* 토픽 토큰을 공유한다 ("AI 도입", "보안 요건" 등). partial-topic 50% threshold는 *합성 데이터에서는* 안전했지만 *실데이터에서는* 노이즈 토큰에 걸렸다.

**결정.** 이 격차를 알면서도 #69를 그대로 머지하되, follow-up PR에서 threshold를 0.66~0.75로 올리거나 single-topic 가드를 추가하는 후속 작업으로 분리. 더 중요한 건 — *이 격차를 사후가 아니라 사전에 발견했다*는 사실. dual-surface가 그 일을 한 거다.

## Makefile workflow

엔지니어 입장에서 두 surface를 다루는 흐름:

```bash
# 1. 평가 실행 — 출력은 reports/real100/, 모두 gitignored
make real-eval

# 2. aggregate-only diff를 PR comment 형식으로 렌더
make real-eval-delta

# 3. PR description에 붙여 리뷰
#    (per-case 정보는 절대 포함 안 됨 — allowlist가 잘라낸다)

# 4. 의사결정 후 baseline aggregate 갱신
make real-eval-baseline-update
```

이 4단계가 *반복 가능한 사이클*이 되도록 Makefile target으로 잠가둔다. ad-hoc "스크립트 실행 → 결과 복사 → PR에 붙이기" 흐름이었다면 매번 *누수 위험*이 있었을 것이다.

## 일반화 — 다른 private-data 프로젝트에 그대로 쓰는 4-step recipe

1. **두 surface의 역할을 *문서가 아니라 파일 경로*로 정의한다.** `eval/config.yaml` vs `eval/*.local.yaml` 같은 컨벤션 한 줄.
2. **`.gitignore`로 전부 차단하고 aggregate 한 파일만 allowlist.** "기본은 닫고 예외만 연다." `!reports/*/baseline.aggregate.json` 패턴.
3. **pre-commit hook으로 우회 시도를 명시 신호로 바꾼다.** `--no-verify` 없이는 못 빠져나가게.
4. **aggregate 추출기를 *명시적 allowlist*로 작성한다.** 새 metric은 allowlist 갱신 PR로 들어와야 한다. 스키마 드리프트 누수 차단.

이 recipe는 RFP DocAgent의 도메인-특수 코드가 아니다. 의료 영상, 사내 문서 검색, 고객 상담 로그 — 어디서든 그대로 동작한다.

## 다음 글에서

[실패 분류로 백로그 생성하기](./) — 실데이터에서 발견된 실패를 6 카테고리로 분류해 GitHub 이슈/PR로 매핑한 방법론. C6 false abstention → 이슈 #69, C4 follow-up loss → 이슈 #71, C2 ambiguity → 이슈 #72 walk-through.

---

- 관련 ADR: [0005](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0005-eval-split-public-synthetic-private-local.md), [0004](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/adr/0004-verifier-retry-policy.md)
- 실데이터 Decision Log: [`docs/private-100-doc-experiments.md`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/docs/private-100-doc-experiments.md)
- 경계 코드: [`.gitignore`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/.gitignore), [`.githooks/pre-commit`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/.githooks/pre-commit), [`scripts/run_real_eval_delta.py`](https://github.com/hskim-solv/BidMate-DocAgent/blob/main/scripts/run_real_eval_delta.py)
- 이전 글: [Extractive를 1급 baseline로 유지하는 이유](../2026-05-extractive-baseline/)
