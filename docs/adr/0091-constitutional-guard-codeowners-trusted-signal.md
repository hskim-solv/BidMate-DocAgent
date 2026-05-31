# 0091: 헌법불변 가드의 trusted signal을 author-writable PR-body marker에서 CODEOWNERS 리뷰로 이전

- **Status**: proposed
- **Date**: 2026-05-31
- **Issue**: [#1701](https://github.com/hskim-solv/BidMate-DocAgent/issues/1701)
- **Related**: [0088](0088-opt-in-staging-self-ship-external-enforcement.md) (P1 opt-in stub lane — `[constitutional-change-ack]` marker 도입), [0090](0090-activate-staging-self-ship-lane-live-enforcement.md) (env-trust 제거 + live protection verify)

## TL;DR

- 헌법불변 가드의 trusted signal을 **author가 직접 쓸 수 있는** PR-body 마커(`[constitutional-change-ack]`)에서, **CODEOWNERS 리뷰**(브랜치 보호의 "Require review from Code Owners" + required-check `check_constitutional_review.py`가 `gh API`로 code-owner(≠PR author) APPROVED 검증)로 이전한다.
- Threat model: GitHub가 **PR author의 self-approval을 차단**하므로, 자율 루프(= PR author)는 이 신호를 스스로 만들 수 없다. PR-body 마커는 루프가 자기 손으로 쓸 수 있어 외부 게이트가 아니었다 — ADR 0090이 제거한 env-trust와 같은 ouroboros 부류.
- 보호 대상 집합을 `_ship_env.py` + `_governance.py` + `.github/CODEOWNERS` 자체로 **확장**한다.
- ADR 0088의 `[constitutional-change-ack]` 마커 메커니즘을 **부분 supersede**한다 (나머지 ADR 0088 불변은 보존).

## 배경

ADR 0088 P1은 `.github/workflows/staging-self-ship-guard.yml`에 헌법불변 가드를 도입했다. 이 가드는 PR이 ship-lane 헌법 파일(`_staging_ship.py`/`_ship_payload_guard.py`/워크플로 자신)을 변경하면, PR body에 `[constitutional-change-ack]` 마커가 있어야 통과시켰다.

이 마커 메커니즘은 ADR 0090이 제거한 env-trust(`BIDMATE_SHIP_PROTECTION_VERIFIED`)와 **구조적으로 동일한 취약점**을 갖는다:

1. **Author-controlled signal (ouroboros).** PR body는 PR author가 쓴다. 자율 staging-self-ship 루프가 PR author일 때, 루프는 `[constitutional-change-ack]`를 자기 PR body에 그냥 써 넣어 가드를 통과시킬 수 있다. 즉 "외부 인간 리뷰"라는 의도된 의미가 author 자신에 의해 만족 가능하므로 **실제 외부 게이트가 아니다**. ADR 0090이 env-trust를 제거하며 "헌법불변의 강제가 in-process(또는 author-writable) 신호에 의존하면 자기 안전장치를 스스로 해체하는 경로가 열린다"고 한 것과 같은 부류다.

2. **인라인 YAML 로직 = 테스트 불가능.** 가드 결정 로직이 워크플로 YAML 안 heredoc에 인라인되어 있어 단위 테스트가 없다 (저장소의 `check_branch_and_issue.py` 패턴 — 테스트 가능한 check-script를 CI가 호출 — 과 어긋남).

## 결정

**헌법불변 가드의 trusted signal을 CODEOWNERS 리뷰로 이전한다:**

1. **`.github/CODEOWNERS` (신규).** ship-lane 헌법 파일을 owner(`@hskim-solv`)에게 매핑한다. 브랜치 보호에서 "Require review from Code Owners"를 켜면, 이 경로를 건드리는 PR은 owner의 리뷰를 요구하고, GitHub가 self-approval을 차단하므로 자율 루프는 자기 PR을 승인할 수 없다. 보호 집합: `_staging_ship.py`, `_ship_env.py`, `_ship_payload_guard.py`, `_governance.py`, `staging-self-ship-guard.yml`, `.github/CODEOWNERS` 자신, `.githooks/pre-commit`. (`agent_loop.py`는 너무 자주 편집되므로 의도적으로 제외 — issue #1701 범위.)

2. **`scripts/check_constitutional_review.py` (신규, 테스트 가능).** `check_branch_and_issue.py` 스타일의 순수 결정 함수 + CLI. 모듈 상수 `PROTECTED_PATHS`(= CODEOWNERS와 동기 유지, 테스트가 parity 강제)와 순수 함수 `requires_owner_approval_violation(changed_files, author_login, approved_reviewer_logins, owner_logins) -> str | None`을 둔다. APPROVING 리뷰어는 `owner_logins`에 속하고 `author_login`과 다를 때만 유효하다 (author가 어쩌다 owner여도 방어적으로 제외 — 자율 루프는 self-approve 불가여야 함). CLI는 `gh api`로 변경 파일/author/APPROVED 리뷰어를 가져오고, CODEOWNERS에서 owner 로그인을 파싱한다. gh-fetching은 injectable seam(`gh_json`/`read_codeowners`)으로 분리해 순수 함수를 네트워크 없이 단위 테스트한다. 위반 시 exit 1, 아니면 exit 0.

3. **워크플로 업데이트.** `staging-self-ship-guard.yml`의 "Constitutional-invariant file-change guard" step이 인라인 YAML 마커 검사 대신 `python scripts/check_constitutional_review.py --pr <number>`를 실행한다. 워크플로에 `pull-requests: read` 권한을 추가한다 (스크립트가 GITHUB_TOKEN으로 gh api 호출). 데이터 경계 스캔 step(`assert_no_raw_payload`)은 불변. `[constitutional-change-ack]` 마커 로직과 그 step의 `PR_BODY` env를 제거한다.

## 결과

**Wins**
- Trusted signal이 author-writable에서 **GitHub 서버가 강제하는 self-approval 차단**으로 이전 — 자율 루프가 신호를 스스로 만들 수 없음. ADR 0090의 env-trust 제거와 같은 부류의 ouroboros 차단.
- 가드 결정 로직이 워크플로 YAML 밖 테스트 가능한 check-script로 분리 — 저장소의 `check_branch_and_issue.py` 패턴과 일치. 순수 함수 단위 테스트로 5개 결정 경로(no-touch / owner-approved / author-approved / non-owner-approved / no-approval) 고정.
- 보호 집합이 `_ship_env.py`(ADR 0090이 도입한 단일 출처 env 격리) + `_governance.py`(LOAD_BEARING 단일 출처) + CODEOWNERS 자신으로 확장 — 가드의 신뢰 기반 자체가 보호됨.
- `PROTECTED_PATHS` ↔ CODEOWNERS parity를 테스트로 강제 — 두 출처가 drift할 수 없음.

**Costs**
- CODEOWNERS 강제는 **브랜치 보호의 "Require review from Code Owners" 설정에 의존**한다 (운영자 GitHub admin 작업). required-check `check_constitutional_review.py`는 APPROVED 리뷰를 독립 검증하지만, 머지 자체를 막는 1차 강제는 브랜치 보호다.
- `gh api` 호출은 네트워크 의존 — rate-limit / API 장애 시 fail-closed(exit 2, blocked-on-user).

**blocked-on-user (이 ADR의 PR에서 명시적으로 하지 않는 것)**
- `main` + `autopilot/integration`(및 P2.2 통합 브랜치)에 브랜치 보호 "Require review from Code Owners" 활성화 (운영자 GitHub admin 작업).
- 이 ADR 자체의 Status `proposed → accepted` 전환.

**Supersession / 관계**
- ADR 0088의 `[constitutional-change-ack]` PR-body 마커 메커니즘을 **부분 supersede**한다 — 마커는 author-writable이라 외부 게이트가 아니므로 CODEOWNERS 리뷰로 교체. ADR 0088의 나머지 불변(staging-only / force-push 금지 / ship-arm 상호배제 / 데이터 경계 / required-check가 외부 강제 권위라는 모델)은 **보존**.
- ADR 0090(live protection verify + env-trust 제거)은 보완 — 같은 ouroboros 부류의 두 번째 author-controlled 신호를 제거.
- ADR 0001·0003·0005는 보존.

## 검토한 대안

- **`[constitutional-change-ack]` 마커 유지.** Reject: PR body는 author가 쓰므로 자율 루프(= author)가 자기 손으로 마커를 써 넣어 게이트를 통과시킬 수 있다 — 외부 게이트가 아님. ADR 0090이 제거한 env-trust와 구조적으로 동일.
- **CODEOWNERS 없이 워크플로 안에서 리뷰 검증만.** Reject: required-check 스크립트가 APPROVED를 검증해도, 브랜치 보호의 Code Owners 요구가 없으면 GitHub UI에서 owner 리뷰 없이 머지 가능. CODEOWNERS + 브랜치 보호가 self-approval 차단의 1차 강제 권위.
- **CODEOWNERS glob matcher 구현(touched path → 해당 owner 정밀 매핑).** Reject: 이 저장소의 모든 보호 경로가 동일 owner에 매핑되므로 전체 owner 로그인 집합을 pool로 쓰는 것과 등가. glob matcher는 불필요한 복잡도.
- **`agent_loop.py`를 보호 집합에 추가.** Reject: 너무 자주 편집되어 모든 PR이 owner 리뷰를 요구하게 됨 — issue #1701 범위 밖.

## Verification

<!-- verifies-key: scripts/check_constitutional_review.py:requires_owner_approval_violation -->

`scripts/check_constitutional_review.py`의 순수 함수 `requires_owner_approval_violation`이 헌법불변 가드 결정을 구현하며, `tests/test_constitutional_review.py`가 5개 결정 경로 + `PROTECTED_PATHS` ↔ `.github/CODEOWNERS` parity + 워크플로가 `[constitutional-change-ack]`를 더 이상 포함하지 않고 `check_constitutional_review.py`를 호출함을 고정한다.

검증 표면:
- `python3 -m pytest tests/test_constitutional_review.py -q` 통과.
- `grep -n "constitutional-change-ack" .github/workflows/staging-self-ship-guard.yml` 결과가 비어 있음 (마커 로직 제거).
- `grep -n "check_constitutional_review.py" .github/workflows/staging-self-ship-guard.yml` 결과가 존재 (테스트 가능 check-script 호출).
- 운영자 준비 완료 후: 브랜치 보호 "Require review from Code Owners" 활성화 시, owner 리뷰 없는 헌법파일 PR이 머지 차단됨을 live e2e로 확인.
