# CORS Issue & Temporary Workaround Record

## 이슈 내용
프론트엔드(Vercel)에서 백엔드(ngrok 터널링)로 API 요청 시 CORS 에러 발생.

## 원인 분석
1. **ngrok 브라우저 경고**: ngrok 무료 플랜 사용 시 발생하는 "Browser Warning" 페이지가 OPTIONS (preflight) 요청을 가로챔.
2. **CORS 정책 위반**: 경고 페이지 응답에 CORS 헤더(`Access-Control-Allow-Origin` 등)가 없어서 브라우저에서 요청이 차단됨.
3. **Credentials 설정**: `allow_credentials=True`와 `allow_origins=["*"]` 조합이 브라우저/프록시 환경에 따라 차단될 수 있음.

## 적용된 임시 해결 방안 (2026-04-09)
**해결 제안 1번 적용**: 프론트엔드 요청 헤더에 ngrok 경고를 무시하는 헤더 추가.
- 헤더 키: `ngrok-skip-browser-warning`
- 헤더 값: `69420` (또는 임의의 값)

## 향후 수정 계획
- 백엔드를 정식 도메인으로 배포하거나, ngrok을 사용하지 않는 환경으로 이전 시 해당 헤더는 프론트엔드 코드에서 제거할 수 있습니다.
- 보안을 위해 정식 배포 시에는 `allow_origins`를 특정 도메인으로 제한하는 설정을 권장합니다.
