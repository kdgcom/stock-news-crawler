# RUN

## codex

### 1) 사전 준비
- Python 3.11+ 설치
- 프로젝트 루트에서 의존성 설치

```powershell
python -m pip install -r requirements.txt
```

### 2) codex_impl 기본 실행 (단일 심볼 의사결정)
- 아래 명령은 `src/codex_impl/app.py`의 `TradingSystem`을 호출해
  하이브리드 신호 생성 + 리스크 체크 + 페이퍼 실행(가능 시) + 매도 제안 생성까지 수행한다.

```powershell
$code = @"
from src.codex_impl import TradingSystem

system = TradingSystem()
result = system.run_symbol(symbol="005930", market="KR", user_id="demo", account_id="paper")

print("decision:", result["signal"].decision)
print("score:", round(result["signal"].score, 4))
print("execution:", result["execution"].status, result["execution"].reason)
print("sell_recommendation:", None if result["sell_recommendation"] is None else result["sell_recommendation"].action)
print("metrics:", result["metrics"])
"@
$code | python -
```

### 3) 수동 매수/매도 입력 API (Cloud Function 핸들러)
- `src/codex_impl/portfolio_api.py`에 핸들러가 구현되어 있다.
- 배포 시 엔드포인트 매핑:
  - `GET /portfolio/input`
  - `POST /portfolio/trades`
  - `GET /portfolio/holdings`

### 4) 로컬에서 핸들러 빠른 확인 (예시)
- Flask/FastAPI 래퍼를 별도로 두고 `portfolio_api.py` 함수를 연결해 테스트한다.
- 핵심 규칙: 매도 제안은 `net_quantity > 0` 보유 종목에서만 생성됨.

### 5) 설정 파일 사용
- 기본값: `src/codex_impl/step01_config.py`
- 사용자 설정 오버라이드(선택):
  - `config/settings.yaml`
  - `config/settings.local.yaml`
