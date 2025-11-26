# start_all.ps1 개요

하는 일:
- 환경변수 `OPENAI_API_KEY`가 비어 있으면 `openai-key.txt`에서 읽어 설정(여전히 없으면 경고).
- 포트 8000을 점유 중인 프로세스를 중지해 오래된 uvicorn이 막지 않게 함.
- `run.ps1`를 최소화된 PowerShell 창에서 실행(백엔드 + admin/user 프런트 개발 서버 기동)하고 계속 유지.
- `StartupWaitSeconds`(기본 10초) 대기 후 `http://localhost:8000/docs`를 헬스체크(베스트 에포트).
- 전달받은 URL로 `run_test.ps1` 실행 후, 그 종료코드를 그대로 반환.
- `run.ps1`에서 뜬 서버는 계속 실행 상태로 둠; 해당 창에서 Ctrl+C나 `Stop-Process -Id <pid>`로 직접 종료.

매개변수:
- `RecognitionUrl` (기본 `http://localhost:8000/api/license-plates`): `run_test.ps1` → `start-manual-capture.ps1`로 전달.
- `MatchUrl` (기본 `http://localhost:8000/api/plates/match`): `run_test.ps1` → `start-manual-capture.ps1`로 전달.
- `StartupWaitSeconds` (기본 `10`): 헬스체크·테스트 실행 전 대기 시간.

사용 예:
- `.\start_all.ps1`
- `.\start_all.ps1 -StartupWaitSeconds 15` (부팅 대기 시간 변경)
- `OPENAI_API_KEY`가 설정돼 있지 않거나 `openai-key.txt`가 없으면 테스트 중 GPT 기반 번호판 인식이 실패함.
