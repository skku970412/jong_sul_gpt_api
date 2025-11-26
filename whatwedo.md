# 작업 로그 / What We Did

## 주요 설정
- `openai-key.txt`: 루트에 두고 OPENAI_API_KEY 한 줄 저장. 백엔드(`config.py`), `run.ps1`, `start_all.ps1`, `run_test.ps1`에서 자동 로드.
- 기본 인식 모드: GPT API (`PLATE_SERVICE_MODE=gptapi`).
- 인식 프롬프트(`PLATE_OPENAI_PROMPT` 기본): "Read only the license plate number from the image. Return just the plate text; keep any hyphen or dash characters."

## 스크립트 변경/추가
- `start-manual-capture.ps1`: 캡처 → 인식/매칭 후 리포트에서 `match=true`면 `start-arduino-workflow.ps1` 자동 실행. 리포트 plate/match 로그 출력 추가.
- `start-manual-capture.bat`, `start-arduino-workflow.bat`: 실행 디렉터리 이동 및 NoProfile 적용.
- `run_test.ps1`: `start-manual-capture.ps1` 호출, URL 전달; `openai-key.txt` 자동 로드.
- `start_all.ps1`: 8000 포트 정리 → `run.ps1` 띄움 → 헬스 체크 → `run_test.ps1` 실행; `openai-key.txt` 자동 로드.
- `tools/check-sample-match.ps1`: 샘플 이미지 인식+매칭 한 번에(OPENAI_API_KEY 필요).
- `tools/test_plate_match.py`: `--use-latest`로 DB 최신 예약 중간 시각 매칭 테스트.
- `.gitignore`: `openai-key.txt` 추가.
- `backend/app/config.py`: OPENAI_API_KEY가 없으면 루트 `openai-key.txt`에서 로드 시도.
- `docs/work-notes.md`: 작업 요약 기록.

## 현재 상태/메모
- 인식 테스트는 `/api/license-plates`에서 200으로 plate `03두 2902` 확인됨(키 정상 적용 시).
- 여러 과거 예약으로 인해 UTC 마이그레이션 경고가 뜨지만 앱은 기동됨.
- 프런트 dev 포트는 점유 시 5173~순차로 올라감(최근 5183/5184).
- 자동 키 로드가 작동하려면 `openai-key.txt`에 실제 키가 있어야 함. 빈 파일이면 500 발생.
- 아두이노 연계: 매칭 성공 시(`match=true`)에만 `start-arduino-workflow.ps1` 실행.

## 사용 예
1) 백엔드/프런트/테스트 한 번에:
   ```powershell
   # openai-key.txt에 키가 들어있다고 가정
   .\start_all.ps1
   ```
2) 수동 테스트만:
   ```powershell
   curl.exe -s -X POST -F "image=@example.jpg" http://localhost:8000/api/license-plates
   ```
3) 수동 캡처+매칭(+아두이노):
   ```powershell
   .\run_test.ps1   # 또는 .\start-manual-capture.ps1 --recognition-url ... --match-url ...
   ```
