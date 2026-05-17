# 0047: 1인 저자 ADR governance — lifecycle SLA + verification 계약

- **Status**: accepted
- **Date**: 2026-05-15
- **Deciders**: hskim
- **Related**: [ADR 0007](./0007-issue-linked-branch-naming.md), issue [#757](https://github.com/hskim-solv/BidMate-DocAgent/issues/757) (A2 번호 예약), issue [#793](https://github.com/hskim-solv/BidMate-DocAgent/issues/793) (B3 verification lint), issue [#817](https://github.com/hskim-solv/BidMate-DocAgent/issues/817) (D1 — 본 ADR), issue [#818](https://github.com/hskim-solv/BidMate-DocAgent/issues/818) (regex follow-up)

## TL;DR

- 1인 저자 ADR 거버넌스 명시화: 4개 기계적 가드 (Deciders 단일, 30일 proposed SLA, Verification 계약, 번호 예약 자동화)
- peer review 부재를 hook + lint 로 대체
- 저자 시점에 ADR 0046 → 0047 번호 충돌 3회 발생, audit 가치 실시간 입증

## 배경

2026-05-15 까지 본 repo 가 2주 동안 1인 저자로 43개+ ADR 누적. ADR 작성 *방법* 규칙은 3개 prose 파일 (`CLAUDE.md`, `docs/engineering-governance.md`, `docs/adr/README.md`) 에 산재 — 거버넌스 자체를 ADR 로 코딩화 안 함. 5월 15일 self-audit (`~/.claude/plans/fizzy-splashing-cherny-adr-governance.md`) 가 3개 구조적 갭 포착:

- **A2** — 번호 예약이 수동, 과거 최소 3회 깨짐 (`0022→0023, 0023→0025, 0029→0030`). issue [#757](https://github.com/hskim-solv/BidMate-DocAgent/issues/757) (PR #765) 가 fix: `--next-adr-number` + `--check-adr-collision` CLI + pre-commit hook
- **B3** — Consequences 가 CI 미검증 메트릭 약속; "Decision Theatre" 위험. issue [#793](https://github.com/hskim-solv/BidMate-DocAgent/issues/793) (PR #796) 가 fix: `## Verification` 섹션 + `<!-- verifies-key: <path>:<key> -->` 마커 + pre-commit lint
- **D1** — ADR 거버넌스용 meta-ADR 부재. 본 ADR 이 닫는 dogfooding 갭

self-audit *중* live race condition 두 개가 표면화 + A2/B3 가치 실시간 검증:

1. 본 ADR draft 중 PR #740 이 병렬 worktree 에서 ADR 0044 예약 (cross-worktree fallback A2 문서화 `gh pr list --search "ADR" --state open` 수동 catch)
2. merge 후 `--next-adr-number` 실행 시 `0044-realN-eval-case-expansion.md` 가 main 에 존재함에도 CLI 가 `0044` 반환 — lowercase-only `ADR_FILENAME_RE` 가 mixed-case slug 거부. issue [#818](https://github.com/hskim-solv/BidMate-DocAgent/issues/818) follow-up 으로 capture.

## 결정

본 repo ADR 거버넌스는 부재 peer review 대체 4개 기계적 가드와 함께 **solo-author-by-design**:

1. **권한은 명시 + 단일.** `Deciders: hskim` 가 유일한 meta-block 저자 필드. `Reviewers` / `Approvers` 필드 추가 안 함 — 본 repo 가 없는 multi-party 권한 함의. 외부 리뷰 (멘토, 전 동료, 코드리뷰 컨설턴트) 요청은 *권장* 이나 *block* 아님. `Deciders: <single name>` 의 정직성이 외부 reader 가 의존할 신호.

2. **Proposed-status lifecycle SLA.** `2026-05-15` 이후 처음 커밋된 `Status: proposed` ADR 은 **30일** 내 해소 (`accepted`, `superseded by NNNN`, 또는 `deprecated`). 해소 = git history mutation 또는 파일에 명시 `## Resolution` 단락 append. 현재 proposed 5개 (`0011 / 0016 / 0023 / 0029 / 0039`) 는 첫 커밋 날짜로 grandfathered. 자동 강제는 follow-up (`_governance.py` `proposed_adr_age()`); SLA 는 지금 normative, 측정 collector 는 나중에.

3. **새 ADR 의 Verification 계약.** `2026-05-15` 이후 처음 커밋된 모든 ADR 은 `## Verification` H2 섹션 + 최소 1개 `<!-- verifies-key: <relative-path>:<key-substring> -->` 마커 포함 ([#793](https://github.com/hskim-solv/BidMate-DocAgent/issues/793) 따라). pre-commit hook (`.githooks/pre-commit`) 이 새로 추가된 파일에만 강제. `2026-05-15` 에 존재한 41개 ADR 은 grandfathered; retrofit 은 per-ADR follow-up PR — 각 retrofit 독립 reviewable.

4. **번호 예약은 기계적.** `python scripts/_governance.py --next-adr-number` 가 filesystem-free 다음 번호 반환. 저자는 또한 `gh pr list --search "ADR" --state open` 실행해 CLI 가 못 보는 cross-worktree 예약 catch 필수 (audit 가 재발견한 실패 모드). pre-commit hook 이 새 ADR 파일 추가 commit 에 `--check-adr-collision` 호출, same-worktree 중복 빠르게 block.

이 4개가 함께 peer review 가 강제할 것을 대체: A2 (#757) 가 "다른 사람이 번호 free 확인했나?" 대체, B3 (#793) 가 "다른 사람이 Consequences claims 도전했나?" 대체, 본 ADR 의 lifecycle + 권한 규칙이 "다른 사람이 merge gate 했나?" 대체.

## 결과

- **1-author 제한이 surface fact 화.** 외부 reader (recruiter, code-reviewer) 가 `Deciders: hskim` 44+ 회 보고 거버넌스 형태 즉시 추론. 분산 권한의 거짓 신호 없음
- **Proposed limbo 가 deadline 획득.** #2 없으면 grandfathered Proposed 5개가 무기한 모호 유지. 30일 SLA 가 새 모든 것에 per-ADR "promote or prune" 결정 강제 — `adr_health.json` 신호 자동 emission 은 follow-up 이나 규칙 자체는 지금 commit
- **Verification grandfather 는 유한 작업.** 41개 retrofit PR (기존 ADR 당 1개) 가 bounded backlog, open-ended cleanup 아님. 각 retrofit 은 `Verification 섹션 + 마커 추가, 동작 변경 없음` — small, parallelizable
- **채용 narrative 정직 표면.** 자기 문서화 "이는 1-author with 기계적 가드" 가 암묵 "우리는 그냥 ADR 작성" 보다 강한 인터뷰 자료
- **Bus factor 1 유지.** 이 규칙 중 어느 것도 두 번째 decision-maker 추가 안 함; 단일성 명시 + 기계적 가드만. 미래 collaborator 합류 시 `Reviewers` 필드는 Status: superseded ADR 에서 추가, silent retrofit 아님

## 검토한 대안

- **ADR 당 외부 reviewer 의무화.** repo 1-author 라 realistic block. `LOAD_BEARING_PATHS` 터치 ADR 에 soft-mandate 가능하나 강제는 여전히 1인 honor. theater 로 거부
- **ADR 작성 완전 중단.** sunk cost (기존 41개 ADR 이 이미 retrieval/answer 계약 / eval 분리 / 기준선 보존 정당화) 가 삭제 불가능. 또한 ADR 이 설계된 load-bearing-decision SoT 로 작동 중
- **CI 의 LLM 기반 reviewer bot.** 오버 엔지니어링. A2/B3 기계적 가드가 이미 갭의 ~80% 닫음. LLM reviewer 는 content (Alternatives 품질, Consequences 정직성) judge — high false-positive 위험 + 지속 prompt 엔지니어링 비용
- **Lifecycle SLA 60d / 90d.** Proposed limbo 가 한 분기 초과 성장 위험. 30d 가 strict 하지만 self-review 시 weekly "promote or prune" framing 강제, annually 아님

## Verification

본 ADR 의 commitment 가 이미 존재하는 구체 코드 경로에 매핑:

<!-- verifies-key: scripts/_governance.py:next_adr_number -->
<!-- verifies-key: scripts/_governance.py:lint_adr_verification -->
<!-- verifies-key: scripts/_governance.py:find_duplicate_adr_numbers -->
<!-- verifies-key: docs/adr/_template.md:Verification -->
<!-- verifies-key: .githooks/pre-commit:lint-adr-consequences -->

읽기 가이드:

- `next_adr_number` — A2 #757 기계적 번호 예약 CLI (결정 #4)
- `lint_adr_verification` — B3 #793 lint, 본 ADR 이 **첫 dogfood** (결정 #3)
- `find_duplicate_adr_numbers` — A2 #757 충돌 감지, pre-commit hook 이 호출
- `_template.md:Verification` — B3 가 추가한 템플릿 섹션; 새 ADR 이 copy
- `.githooks/pre-commit:lint-adr-consequences` — 새 ADR 파일에 #3 강제하는 hook 라인

repo root 에서 `python3 scripts/_governance.py --lint-adr-consequences docs/adr/0047-solo-author-adr-governance.md` 실행이 exit 0 필수 — 위 모든 마커가 기존 파일의 기존 키로 resolve. 미래 refactor 가 이들 중 어느 것이든 rename 하면 (예: `next_adr_number` → `next_adr_id`) 본 ADR 이 자신의 lint 실패, rename PR 가 두 표면 lockstep 업데이트 필수.

## Live race history (본 ADR 자체 생성에 대한 post-mortem 노트)

본 ADR 은 3-step audit (A2 #757 → B3 #793 → D1 #817) 의 D1 으로 작성. 3개 모두 ship 한 self-paced 루프 중:

1. PR #740 가 ADR 0044 (`0044-realN-eval-case-expansion.md`) 예약 — 본 branch 첫 commit 전 수동 catch; draft 0044 → 0046 renumber
2. A2 merge 후, regex 가 mixed-case `realN` slug 거부해 0044 파일이 main 에 존재함에도 `--next-adr-number` 가 `0044` 반환. follow-up issue #818 로 capture
3. 본 branch 가 0046 번호로 PR #820 push 후, PR #824 가 다른 ADR 0046 (`0046-ood-evaluation-domain-selection.md`) merge + PR #766 가 0045 (`0045-rag-core-leaf-migration-plan.md`) merge. GitHub 가 PR `CONFLICTING` flag. 0046 → 0047 renumber + rebase

90분 window 의 3개 live 충돌이 audit 전제 검증: 이 단일 ADR 가 자신의 작성 중 audit 가 catch 한 실패 모드 **3회** 만남. 기계적 가드 (A2 CLI + B3 lint + `gh pr list` cross-check) 가 해소 비용을 "silent merge 충돌" 에서 "rebase + renumber + comment" 로 축소. 없었다면 ADR 0046 이 두 다른 body 로 두 번 ship, regex 버그 (#818) 가 여전히 invisible.
