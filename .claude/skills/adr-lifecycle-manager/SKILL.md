---
name: adr-lifecycle-manager
description: |
  Resolve proposed-status ADRs against ADR 0047's 30-day SLA. Reads the `python3 scripts/_governance.py --proposed-adr-age` collector (PR #1094), surfaces OVER_SLA / approaching-SLA proposed ADRs, and drives a per-ADR resolution decision — promote (accepted) / supersede by NNNN / deprecate / append `## Resolution` / keep-open-with-justification — with explicit confirmation, then syncs the README index row + Verification lint and hands off to ship-pr. Post-authoring lifecycle only; no helper code, orchestrates existing _governance.py flags.

  Trigger phrases: "ADR lifecycle", "proposed ADR 정리", "proposed ADR SLA 점검", "ADR 30일 SLA", "오래된 proposed ADR 해소", "proposed ADR promote/supersede", "adr-lifecycle-manager". Trigger when the user wants to RESOLVE aging proposed ADRs (not author new ones). Trigger even if the user does not say "skill".

  Do NOT trigger for: authoring a NEW ADR or reserving its number (use `ship-pr`), drafting an ADR from eval results (use the `eval-to-adr-bridge` agent), mapping an ADR to senior-engineering signals for portfolio (use `adr-portfolio-signals`), generic PR shipping (use `ship-pr`), or regenerating the eval baseline (use `eval-baseline-regen`).
---

# /adr-lifecycle-manager — proposed ADR 30일 SLA 해소 (판단 레이어)

ADR 0047이 선언한 30일 proposed-status SLA를 해소하는 skill. **기계적 탐지는 이미 [`python3 scripts/_governance.py --proposed-adr-age`](../../../scripts/_governance.py)(PR #1094)가 처리** — 이 skill은 그 위에서 OVER_SLA proposed ADR을 어떻게 해소할지 **판단**(promote / supersede / deprecate / Resolution / keep-open)을 구동한다. 코드 helper 작성 금지(기존 `_governance.py` 플래그만 호출). ADR 작성·번호예약은 out of scope(ship-pr). 로컬·가역 편집(Status 변경 + README 동기화)까지만 하고 push/PR/merge는 `ship-pr` 에 위임.

## Scope

- `docs/adr/*.md` 중 **Status: proposed** 인 것의 사후 lifecycle 한정. ADR 신규 작성·번호 예약은 ship-pr / eval-to-adr-bridge 담당.
- collector(`--proposed-adr-age`)가 단일 탐지 출처. skill은 그 출력을 해석·판단만 — 자체 나이 계산/파싱 재구현 금지.
- grandfathered(2026-05-15 이전 첫 커밋, 0047 면제)는 기본적으로 건드리지 않음 — 사용자가 명시 요청 시만.
- Helper code inline 작성 금지. 새 collector 로직 필요 시 별개 PR(`_governance.py`)로 선행.

## Workflow

1. **탐지** — `python3 scripts/_governance.py --proposed-adr-age` 실행. 출력 컬럼: `NNNN<TAB>age_days<TAB>flag(OVER_SLA/grandfathered/ok)<TAB>first_commit<TAB>filename`. OVER_SLA 우선, 그다음 approaching(age ≥ 23일 = SLA−7) 표면화. grandfathered/ok 는 정보용.
2. **대상 선정 (gate)** — 해소할 ADR을 사용자와 확정. OVER_SLA 0건이면 "해소 대상 없음" 보고 후 종료. 다건이면 한 lifecycle PR로 묶을지(one concern) 확인.
3. **per-ADR 판단 (각 건 명시 확인)** — 해당 ADR 본문을 읽고 5개 중 택1 제시:
   - **promote** → `Status: accepted` (결정 유효·검증됨). post-2026-05-15 ADR이면 먼저 `--lint-adr-consequences docs/adr/<file>` 로 Verification 마커가 실제 wired 인지 확인.
   - **supersede** → `Status: superseded by NNNN`. 대체 ADR이 있으면 그 번호, 없으면 `--next-adr-number` 로 예약 번호만 안내 — 새 ADR **작성은 ship-pr/author 몫**, 이 skill은 status 포인터만 설정.
   - **deprecate** → `Status: deprecated` (대체 없이 폐기).
   - **resolve-in-place** → `## Resolution` 단락 append(0047: 해소 = status mutation 또는 Resolution append). 결과·근거 1문단.
   - **keep-open + justify** → 아직 열려있으면 거부가 아니라 본문에 **명시 사유** append(방치 아닌 의식적 연장).
   - **자동 promote/supersede 절대 금지** — 항상 사용자 확인.
4. **편집 + 동기화** — 선택된 해소를 ADR Status 블록에 적용. Status 문자열이 바뀌면 [docs/adr/README.md](../../../docs/adr/README.md) 인덱스 row의 status 컬럼도 **같은 커밋**에서 갱신 → `python3 scripts/_governance.py --check-adr-readme-parity docs/adr/<file>` 로 parity 확인.
5. **로컬 검증 (gate)** — `bash scripts/test.sh`(특히 `test_no_unlinked_adr_files_on_disk` + collector 테스트). post-2026-05-15 ADR 편집 시 `--lint-adr-consequences` 통과 확인. commit `chore(adr): resolve proposed SLA — <NNNN> <action> (closes #N)`(다건이면 요약).
6. **ship-pr 핸드오프** — "로컬 lifecycle 편집 완료. `/ship-pr` 로 push+PR" 안내. **주의: `docs/adr/` 는 load-bearing** 이므로 resolution PR 은 §5b 필수 — 단 Status 변경은 검색/검증/답변 path 무영향이라 "동작 변화 없음" 명시로 충족.

## Approval-gate language

go-ahead(진행): "진행" / "ㄱㄱ" / "ㅇㅋ" / "ok" / "go". 질문(답변만, 실행 금지): "?" / "promote?" / "해소할까?". 불확실하면 묻고 실행하지 않음. 대상 선정(2)·per-ADR 판단(3)·commit 은 명시 승인 후.

## When the user pushes back

- **"전부 그냥 accepted 로 promote 해"** → 강한 경고. promote는 "결정이 검증됐다"는 신호 — 무검증 일괄 promote는 ADR을 Decision Theatre로 되돌림(0047이 막으려던 바). 각 건 최소 1줄 근거 요구.
- **"grandfathered 도 정리해"** → 가능하나 0047 면제 대상임을 명시 후 진행(면제는 normative 결정).
- **"supersede 할 새 ADR 도 여기서 써줘"** → 거부. ADR 작성·번호예약은 ship-pr / author 몫(조기 범위 확장 금지). 이 skill은 `superseded by NNNN` 포인터만.
- **"README parity 무시"** → 거부. status 불일치는 `test_no_unlinked_adr_files_on_disk` CI를 머지 시 red로 만들어 모든 open PR에 cascade(이슈 #730/#732/#750 전례).

## References

- ADR 0047 — 1인 저자 ADR governance: 30일 proposed SLA + Verification 계약 + 번호예약.
- [scripts/_governance.py](../../../scripts/_governance.py) — `--proposed-adr-age`(PR #1094, 탐지), `--lint-adr-consequences`(#793), `--check-adr-readme-parity`(#803), `--next-adr-number`(supersede 대상 번호).
- [docs/adr/README.md](../../../docs/adr/README.md) — 인덱스 row(status 컬럼 동기화 대상).
- [docs/adr/_template.md](../../../docs/adr/_template.md) — Status 블록 + Verification 형식.
- [.claude/skills/ship-pr/SKILL.md](../ship-pr/SKILL.md) — push/PR/merge 핸드오프 + approval-gate 컨벤션.
- [.claude/skills/eval-baseline-regen/SKILL.md](../eval-baseline-regen/SKILL.md) — 동일 패턴(기계적 도구 위 판단 레이어 + ship-pr 핸드오프).

## What this skill does NOT do

- Does NOT write helper code — 기존 `_governance.py` 플래그만 오케스트레이션.
- Does NOT author new ADRs or reserve numbers — ship-pr / eval-to-adr-bridge 담당. supersede 시 `superseded by NNNN` 포인터만.
- Does NOT auto-promote/supersede — 항상 사용자 per-ADR 확인.
- Does NOT touch grandfathered ADRs by default — 0047 면제, 명시 요청 시만.
- Does NOT push / open PR / merge — ship-pr 담당.
- Does NOT hard-gate CI on SLA violation — 탐지+판단만, 강제는 별도 정책.
