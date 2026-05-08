# Reproducible Harness

이 harness는 기존 README 기본 흐름을 바꾸지 않고, smoke 실행에 필요한 입력 config, 로그, 예측, 평가 요약을 run 단위 디렉터리에 묶는다. 목적은 benchmark/ablation 확장 전에도 한 명령으로 재현 가능한 작은 실행 단위를 남기는 것이다.

## 실행

```bash
python3 scripts/run_harness.py --config harness/smoke.yaml
```

동일한 smoke harness는 Make target으로도 실행할 수 있다.

```bash
make harness-smoke
```

고정 run id를 사용하거나 기존 run을 덮어쓰려면 다음처럼 실행한다.

```bash
python3 scripts/run_harness.py \
  --config harness/smoke.yaml \
  --run_id issue25_smoke_test \
  --force
```

## Run ID와 artifact layout

`--run_id`를 생략하면 `<config_id>_YYYYMMDDTHHMMSSZ` 형식으로 생성한다. 기본 artifact root는 `artifacts/runs`이며, 전체 산출물은 `artifacts/runs/<run_id>/` 아래에 저장된다.

```text
artifacts/runs/<run_id>/
  run_manifest.json
  config_snapshot.json
  summary.json
  predictions.jsonl
  errors.jsonl
  index/index.json
  outputs/answer.json
  metrics/eval_summary.json
  logs/index.log
  logs/query.log
  logs/eval.log
```

`artifacts/runs/`는 Git 추적 대상이 아니다. 공개 synthetic smoke라도 raw prediction과 로그는 로컬 검증 산출물로 유지한다.

## 스키마

`run_manifest.json`은 다음 필드를 포함한다.

- `schema_version`: manifest schema version
- `run_id`: 실행 식별자
- `generated_at`: manifest 생성 시각
- `git_commit`, `git_dirty`: 실행 시점의 Git 상태
- `config_hash`: `config_snapshot.json`의 deterministic hash
- `config_snapshot_path`: 저장된 config snapshot 경로
- `artifacts`: 주요 산출물 경로
- `commands`: index/query/eval에 사용한 실제 command token
- `status`: `passed` 또는 `failed`
- `metrics`: `metrics/eval_summary.json`의 핵심 metric snapshot

`summary.json`은 다음 필드를 포함한다.

- `run_id`
- `status`
- `started_at`, `ended_at`
- `steps`: 각 단계 command, log path, return code, status
- `artifact_dir`
- `metrics_path`
- `errors_path`

`errors.jsonl`은 실패가 없어도 생성한다. 성공한 실행에서는 빈 파일이며, 실패한 실행에서는 실패 step, return code, log path, command를 JSONL로 기록한다.

## Smoke 범위

`harness/smoke.yaml`은 공개 synthetic RFP만 사용하고 hashing embedding으로 인덱스를 만든다. `harness/smoke_eval.yaml`은 작은 고정 case set만 포함한다.

- 단일 문서 보안 요구사항
- 기관 A/B AI 요구사항 비교

전체 품질 평가는 계속 `eval/run_eval.py --config eval/config.yaml`과 benchmark flow가 담당한다.
