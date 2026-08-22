# MCP 실연결 검증 결과

> 이 파일은 `python3 -m mcp_server.verify_connection` 의 실행 출력이다.
> **누구나 같은 명령으로 재현할 수 있다.** 심사 시연 중에도 그 자리에서 돌릴 수 있다.
>
> 검증 항목
> 1. Claude Desktop 설정 파일이 있는지, 커맨드·경로가 실제로 유효한지
> 2. Claude Desktop 로그에 실제 연결 기록이 있는지
> 3. **설정 파일의 커맨드 그대로** stdio 로 MCP 프로토콜을 주고받는지
> 4. DEMO.md 의 사투리 질의가 납득 가능한 답을 내는지
> 5. 라우팅 회귀 통과율
>
> Claude Desktop 이 없는 환경(CI, 심사위원 노트북)에서는 1·2가 `skip` 되고
> 3·4·5 만 돌아간다. 그것만으로도 "표준 MCP 클라이언트가 붙을 수 있다"는 근거가 된다.

## 실행 결과

```
Voisso MCP 실연결 검증
  저장소 : /Users/harudev/Desktop/dev/junctionX
  python : 3.10.10
  mcp SDK: 2.0.0

── 1. Claude Desktop 설정 파일 ───────────────────────────────────
  ok    설정 파일 존재  — /Users/harudev/Library/Application Support/Claude/claude_desktop_config.json
  ok    mcpServers.voisso-gb 등록됨
  ok    command 실행 가능: python3  — /Library/Frameworks/Python.framework/Versions/3.10/bin/python3
  ok    env PYTHONPATH  — /Users/harudev/Desktop/dev/junctionX
  ok    env VOISSO_DATA_DIR  — /Users/harudev/Desktop/dev/junctionX/data

── 2. Claude Desktop 연결 로그 ───────────────────────────────────
  ok    Server started and connected successfully  — 2026-08-22T09:52:08.120Z
  ok    클라이언트가 initialize 호출  — 1회 (현재 연결)
  ok    클라이언트가 tools/list 호출  — 1회 (현재 연결)
  ok    현재 연결에 오류 없음  — 0건 (이전 세션 종료 기록 1건은 제외)
  ok    서버 기동 배너(stderr)  — [voisso-gb] 데이터 96개 부서 로드 (source=voisso.data.load_departments())

── 3. stdio MCP 프로토콜 왕복 (설정 파일의 커맨드 그대로) ─────────────────────
  실행: python3 -m mcp_server   env={'PYTHONPATH': '/Users/harudev/Desktop/dev/junctionX', 'VOISSO_DATA_DIR': '/Users/harudev/Desktop/dev/junctionX/data'}
  ok    initialize  — voisso-gb 0.1.0  (0.29s)
  ok    tools/list  — 6종: find_department, get_department, list_departments, normalize_dialect, to_dialect, submit_complaint
  ok    tools/call list_departments  — count=1 source=voisso.data.load_departments()

── 4. DEMO.md 사투리·구어체 질의 ─────────────────────────────────────
  DEMO.md 에서 7개 질의를 뽑아 그대로 호출한다.

  ok    [ 59.6ms] 우리 동네 하수구가 막혔는데 어데 전화하믄 되노?  — 단독 배정 0.74 기후환경국 맑은물정책과 / 주무관
           근거: ◦ 하수도분야 국도비 보조사업 예산 및 추진 ◦ 하수도사업 재원협의 및 총사업비변경 관련 업무 ◦ 하수도 재난재해대책(호우, 태풍 등) 
  ok    [  1.6ms] 집 앞에 물이 안 빠지고 자꾸 고여서 큰일이에요  — 단독 배정 0.70 기후환경국 맑은물정책과 / 주무관
           근거: ◦ 하수도분야 국도비 보조사업 예산 및 추진 ◦ 하수도사업 재원협의 및 총사업비변경 관련 업무 ◦ 하수도 재난재해대책(호우, 태풍 등) 
  ok    [  4.0ms] 농로가 유실됐다 카는데 어느 과 소관이고?  — 단독 배정 0.70 농축산유통국 스마트농업혁신과 / 주무관
           근거: ◦재배정사업관리(수질, TM/TC, 수리시설개보수) ◦저수지관리(저수율, 국가안전대진단) ◦사업비 교부 및 자체사업 예산관리 ◦지진(내진) 
  ok    [  2.3ms] 경로당 지원 사업은 누가 담당하노?  — 단독 배정 0.89 복지건강국 어르신복지과 / 주무관
           근거: 경로당 광역지원센터 업무
  ok    [  1.3ms] 산불 예방 관련해서 물어볼 데가 어디고?  — 단독 배정 1.00 산림자원국 산림정책과 / 주무관
           근거: 산불방지 인력 및 시설‧장비 관리․운영, 산불예방 등
  ok    [  0.5ms] 우리 동네 가로등이 며칠째 안 들어와요  — 시군 민원실 안내 (도청 부서 배정 안 함)
           근거: 민원인이 어느 시·군에 사는지 먼저 확인한 뒤, 해당 시·군청 민원실로 안내하세요. 시·군 번호를 모르면 경상북도청 대표번호 1522-012
  ok    [  0.5ms] 빙하 탐사선 견인은 누가 담당하노?  — 매칭 0건 → 대표번호 안내
           근거: 96개 부서 사무분장 어디에도 일치하는 담당업무가 없습니다. 추측해서 배정하지 말고 경북도청 대표번호로 안내하세요.

── 5. 라우팅 회귀 (표현 변형 포함) ──────────────────────────────────────
  ok    회귀 통과율  — 132/132 = 100.0%
  ok    표현 변형 그룹 전원 통과  — 13/13 그룹

==============================================================
결과: 22/22 통과, 0건 건너뜀 (실패 0)
```

## PSTN 관련 정직한 고지

이 검증은 **MCP 서버**에 대한 것이다. 실제 전화망(PSTN) 연동은 별개이며 H3 과제다.
데모의 통화 화면은 브라우저 시뮬레이션이다.
