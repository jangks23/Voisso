/**
 * Voisso 대시보드 — 개발용 샘플 민원카드
 *
 * docs/CONTRACT.md 5절 "민원카드 스키마"를 그대로 따른다.
 * server/ 의 GET /api/complaints 가 뜨면 app.js 가 자동으로 실제 API로 전환하고
 * 이 파일은 사용되지 않는다. (전환 로직: app.js > loadComplaints)
 *
 * 전화번호는 계약서 3절 개인정보 처리 규칙에 따라 PHONE_xxxx 토큰만 담는다.
 * 실번호 매핑은 data/private/phone_map.json (gitignore) 에만 존재하며,
 * 매핑이 없으면 런타임은 경북도청 대표번호 1522-0120 으로 폴백한다.
 */
window.VOISSO_MOCK_COMPLAINTS = [
  {
    id: "0417",
    created_at: "2026-08-21T14:32:00Z",
    duration_sec: 108,
    summary: "안동시 옥동 주택가 배수 불량, 강우 시 반복 침수",
    category: "도로·하수 유지관리",
    assigned: {
      department_id: "gb-6470911-6470934",
      full_name: "건설도시국 도로과",
      position: "주무관",
      phone_token: "PHONE_0421",
      evidence: "우수관로 정비 및 배수시설 유지관리, 도로 침수 취약구간 점검·보수"
    },
    alternatives: [
      {
        full_name: "환경산림자원국 물관리과",
        department_id: "gb-6470955-6470961",
        position: "주무관",
        phone_token: "PHONE_0388",
        score: 0.71,
        evidence: "하천 정비 및 수해 상습지 개선사업 추진"
      },
      {
        full_name: "안전행정실 자연재난과",
        department_id: "gb-6470702-6470715",
        position: "주무관",
        phone_token: "PHONE_0119",
        score: 0.54,
        evidence: "호우·태풍 등 자연재난 예방 및 피해복구 지원"
      }
    ],
    caller: { name_masked: "김○○", phone_masked: "010-****-4471" },
    transcript: [
      { role: "agent", standard: "안녕하세요, 경상북도청 민원 안내입니다. 어떤 일로 전화 주셨어요?", dialect: "안녕하시니껴, 경상북도청 민원 안냅니더. 무신 일로 전화 주셨는교?" },
      { role: "caller", dialect: "아이고 우리 동네가 비만 오마 물이 안 빠져가 마당까지 차뿌요. 옥동인데 벌씨로 시 번째라예.", standard: "저희 동네가 비만 오면 물이 안 빠져서 마당까지 찹니다. 옥동인데 벌써 세 번째예요." },
      { role: "agent", standard: "안동시 옥동 말씀이시죠? 물이 고이는 곳이 도로인가요, 집 앞 배수구인가요?", dialect: "안동시 옥동 말씸이시지예? 물이 고이는 데가 길인교, 집 앞 배수구인교?" },
      { role: "caller", dialect: "길가에 하수구가 막히뿟는지 물이 역류해가 올라온다카이. 우리 집만 그른 기 아이고 골목 전체가 그래요.", standard: "길가 하수구가 막혔는지 물이 역류해서 올라옵니다. 저희 집만 그런 게 아니고 골목 전체가 그래요." },
      { role: "agent", standard: "알겠습니다. 침수 시작된 시점이 언제쯤이신가요?", dialect: "알겠심더. 물 차기 시작한 게 언제쯤인교?" },
      { role: "caller", dialect: "장마 시작하고부텀이라예. 한 보름 됐지 싶으다.", standard: "장마 시작하고부터입니다. 한 보름 됐지 싶어요." },
      { role: "agent", standard: "우수관로와 배수시설 담당인 건설도시국 도로과로 접수해 드리겠습니다. 접수번호는 0417번입니다.", dialect: "우수관로캉 배수시설 맡은 건설도시국 도로과로 접수해 드리겠심더. 접수번호는 0417번입니더." }
    ]
  },
  {
    id: "0416",
    created_at: "2026-08-21T13:05:00Z",
    duration_sec: 142,
    summary: "영주시 단산면 농로 유실로 경운기 진입 불가, 수확기 전 복구 요청",
    category: "농업기반·농로 정비",
    assigned: {
      department_id: "gb-6470880-6470893",
      full_name: "농축산유통국 농업정책과",
      position: "주무관",
      phone_token: "PHONE_0233",
      evidence: "농업생산기반시설(농로·용배수로) 정비 및 재해복구 사업 관리"
    },
    alternatives: [
      {
        full_name: "건설도시국 건설과",
        department_id: "gb-6470911-6470928",
        position: "주무관",
        phone_token: "PHONE_0410",
        score: 0.63,
        evidence: "도로·교량 등 건설공사 시행 및 유지관리"
      },
      {
        full_name: "안전행정실 자연재난과",
        department_id: "gb-6470702-6470715",
        position: "주무관",
        phone_token: "PHONE_0119",
        score: 0.49,
        evidence: "호우·태풍 등 자연재난 예방 및 피해복구 지원"
      }
    ],
    caller: { name_masked: "권○○", phone_masked: "010-****-2019" },
    transcript: [
      { role: "agent", standard: "안녕하세요, 경상북도청 민원 안내입니다. 말씀하세요.", dialect: "안녕하시니껴, 경상북도청 민원 안냅니더. 말씸하이소." },
      { role: "caller", dialect: "우리 밭에 들어가는 농로가 지난 비에 씻기가 다 무너져뿟다. 경운기가 몬 들어간다카이.", standard: "저희 밭으로 들어가는 농로가 지난 비에 쓸려서 다 무너졌습니다. 경운기가 못 들어갑니다." },
      { role: "agent", standard: "위치가 어디신가요?", dialect: "위치가 어데인교?" },
      { role: "caller", dialect: "영주시 단산면이라예. 사과밭 있는 데. 인자 곧 수확인데 길이 없으이 우짜노.", standard: "영주시 단산면입니다. 사과밭 있는 곳이요. 이제 곧 수확인데 길이 없으니 어떡합니까." },
      { role: "agent", standard: "유실된 구간 길이가 대략 어느 정도인지 아시나요?", dialect: "떠내리간 구간이 대충 어느 정도 되는교?" },
      { role: "caller", dialect: "한 이십 미터쯤 될끼라. 옆에 축대도 같이 내려앉았고.", standard: "한 이십 미터쯤 될 겁니다. 옆에 축대도 같이 내려앉았고요." },
      { role: "agent", standard: "수확기 전 복구가 필요한 건으로 표시해서 농업정책과에 전달하겠습니다.", dialect: "수확기 전에 고치야 되는 건으로 표시해가 농업정책과에 전달하겠심더." }
    ]
  },
  {
    id: "0415",
    created_at: "2026-08-21T11:47:00Z",
    duration_sec: 96,
    summary: "포항시 청하면 마을버스 노선 폐지 후 읍내 병원 통원 곤란",
    category: "대중교통 노선",
    assigned: {
      department_id: "gb-6470911-6470941",
      full_name: "건설도시국 교통정책과",
      position: "주무관",
      phone_token: "PHONE_0447",
      evidence: "농어촌버스 노선 조정·인가 및 벽지노선 운행 지원"
    },
    alternatives: [
      {
        full_name: "복지건강국 노인복지과",
        department_id: "gb-6470820-6470831",
        position: "주무관",
        phone_token: "PHONE_0512",
        score: 0.42,
        evidence: "노인 교통·이동 지원사업 및 경로당 운영 지원"
      }
    ],
    caller: { name_masked: "박○○", phone_masked: "010-****-8830" },
    transcript: [
      { role: "agent", standard: "안녕하세요, 경상북도청 민원 안내입니다.", dialect: "안녕하시니껴, 경상북도청 민원 안냅니더." },
      { role: "caller", dialect: "우리 마실 들어오던 버스가 없어져뿌가 병원을 몬 간다. 택시 부르마 한 번에 이만 원이라.", standard: "저희 마을 들어오던 버스가 없어져서 병원을 못 갑니다. 택시 부르면 한 번에 이만 원이에요." },
      { role: "agent", standard: "어느 마을이신지 말씀해 주시겠어요?", dialect: "어느 마실인지 말씸해 주시겠는교?" },
      { role: "caller", dialect: "포항 청하면이라예. 하루 두 번 들어오던 기 지난달부터 뚝 끊깄다.", standard: "포항 청하면입니다. 하루 두 번 들어오던 게 지난달부터 뚝 끊겼습니다." },
      { role: "agent", standard: "노선 조정 담당인 교통정책과로 접수하겠습니다. 수요응답형 버스 안내도 함께 요청드릴게요.", dialect: "노선 조정 맡은 교통정책과로 접수하겠심더. 부르마 오는 버스 안내도 같이 요청해 놓겠심더." }
    ]
  },
  {
    id: "0414",
    created_at: "2026-08-21T10:20:00Z",
    duration_sec: 173,
    summary: "의성군 단밀면 독거 어르신 안부확인 중단, 돌봄 재연계 요청",
    category: "노인 돌봄",
    assigned: {
      department_id: "gb-6470820-6470831",
      full_name: "복지건강국 노인복지과",
      position: "주무관",
      phone_token: "PHONE_0512",
      evidence: "노인맞춤돌봄서비스 운영 및 독거노인 안전확인 사업 총괄"
    },
    alternatives: [
      {
        full_name: "복지건강국 복지정책과",
        department_id: "gb-6470820-6470824",
        position: "주무관",
        phone_token: "PHONE_0501",
        score: 0.66,
        evidence: "취약계층 복지 사각지대 발굴 및 통합사례관리"
      },
      {
        full_name: "복지건강국 건강증진과",
        department_id: "gb-6470820-6470840",
        position: "주무관",
        phone_token: "PHONE_0533",
        score: 0.38,
        evidence: "방문건강관리 및 만성질환 예방관리 사업"
      }
    ],
    caller: { name_masked: "이○○", phone_masked: "010-****-1157" },
    transcript: [
      { role: "agent", standard: "안녕하세요, 경상북도청 민원 안내입니다.", dialect: "안녕하시니껴, 경상북도청 민원 안냅니더." },
      { role: "caller", dialect: "저번까지는 생활지원사가 일주일에 두 분썩 와가 안부 봐 줬는데 두 달째 안 온다카이.", standard: "저번까지는 생활지원사가 일주일에 두 번씩 와서 안부를 봐 줬는데 두 달째 안 옵니다." },
      { role: "agent", standard: "혹시 담당 기관에서 연락받으신 내용은 없으셨나요?", dialect: "혹시 맡은 기관에서 연락받은 기 없었는교?" },
      { role: "caller", dialect: "아무 말도 없더라. 내 혼자 사는데 무슨 일 생기마 우얄란지 걱정이라예.", standard: "아무 말도 없었어요. 저 혼자 사는데 무슨 일 생기면 어쩌나 걱정입니다." },
      { role: "agent", standard: "어르신 사시는 곳이 의성군 단밀면 맞으실까요?", dialect: "어르신 사시는 데가 의성군 단밀면 맞는교?" },
      { role: "caller", dialect: "맞다. 팔십둘이고 무릎이 안 좋아가 밖에도 잘 몬 나간다.", standard: "맞습니다. 여든둘이고 무릎이 안 좋아서 밖에도 잘 못 나갑니다." },
      { role: "agent", standard: "노인맞춤돌봄서비스 담당 부서로 재연계 요청드리겠습니다. 오늘 중으로 연락드릴 수 있게 표시해 두겠습니다.", dialect: "노인맞춤돌봄서비스 맡은 부서로 다시 연결해 달라 하겠심더. 오늘 안으로 연락 가게 표시해 놓겠심더." }
    ]
  },
  {
    id: "0413",
    created_at: "2026-08-21T09:38:00Z",
    duration_sec: 84,
    summary: "울진군 북면 야산 인근 논두렁 소각 목격, 산불 위험 신고",
    category: "산불 예방",
    assigned: {
      department_id: "gb-6470955-6470978",
      full_name: "환경산림자원국 산림보호과",
      position: "주무관",
      phone_token: "PHONE_0777",
      evidence: "산불 예방·진화 대책 수립 및 불법 소각행위 단속"
    },
    alternatives: [
      {
        full_name: "안전행정실 사회재난과",
        department_id: "gb-6470702-6470719",
        position: "주무관",
        phone_token: "PHONE_0126",
        score: 0.58,
        evidence: "화재 등 사회재난 예방 및 대응체계 운영"
      },
      {
        full_name: "환경산림자원국 환경정책과",
        department_id: "gb-6470955-6470958",
        position: "주무관",
        phone_token: "PHONE_0301",
        score: 0.35,
        evidence: "대기환경 개선 및 불법 소각 미세먼지 저감 대책"
      }
    ],
    caller: { name_masked: "최○○", phone_masked: "010-****-6602" },
    transcript: [
      { role: "agent", standard: "안녕하세요, 경상북도청 민원 안내입니다.", dialect: "안녕하시니껴, 경상북도청 민원 안냅니더." },
      { role: "caller", dialect: "저 건너 논두렁에서 불로 놨는데 바람이 마이 부가 산 쪽으로 넘어갈 판이라예.", standard: "저 건너 논두렁에서 불을 놓았는데 바람이 많이 불어서 산 쪽으로 넘어갈 판입니다." },
      { role: "agent", standard: "위치가 울진군 어디쯤이신가요?", dialect: "위치가 울진군 어데쯤인교?" },
      { role: "caller", dialect: "북면 들어가는 길옆이라. 지금도 연기가 시커멓게 올라온다.", standard: "북면 들어가는 길옆입니다. 지금도 연기가 시커멓게 올라옵니다." },
      { role: "agent", standard: "긴급 건으로 산림보호과에 즉시 전달하겠습니다. 가까이 가지 마시고 안전한 곳에 계세요.", dialect: "급한 건으로 산림보호과에 바로 전달하겠심더. 가차이 가지 마시고 안전한 데 계시이소." }
    ]
  },
  {
    id: "0412",
    created_at: "2026-08-21T08:55:00Z",
    duration_sec: 119,
    summary: "상주시 공성면 하천변 폐기물 무단투기 반복, 단속 요청",
    category: "폐기물 관리",
    assigned: {
      department_id: "gb-6470955-6470969",
      full_name: "환경산림자원국 자원순환과",
      position: "주무관",
      phone_token: "PHONE_0344",
      evidence: "생활폐기물 처리 및 폐기물 불법 투기 단속·과태료 부과"
    },
    alternatives: [
      {
        full_name: "환경산림자원국 물관리과",
        department_id: "gb-6470955-6470961",
        position: "주무관",
        phone_token: "PHONE_0388",
        score: 0.52,
        evidence: "하천 수질 관리 및 오염원 점검"
      },
      {
        full_name: "환경산림자원국 환경정책과",
        department_id: "gb-6470955-6470958",
        position: "주무관",
        phone_token: "PHONE_0301",
        score: 0.44,
        evidence: "환경오염 행위 지도·점검 및 환경감시 활동"
      }
    ],
    caller: { name_masked: "정○○", phone_masked: "010-****-9028" },
    transcript: [
      { role: "agent", standard: "안녕하세요, 경상북도청 민원 안내입니다.", dialect: "안녕하시니껴, 경상북도청 민원 안냅니더." },
      { role: "caller", dialect: "밤마다 누가 트럭으로 실고 와가 하천 옆에 건축 쓰레기로 갖다 버린다카이.", standard: "밤마다 누가 트럭으로 실어 와서 하천 옆에 건축 쓰레기를 갖다 버립니다." },
      { role: "agent", standard: "장소가 상주시 어디신지 알려 주시겠어요?", dialect: "장소가 상주시 어덴지 알케 주시겠는교?" },
      { role: "caller", dialect: "공성면 다리 밑이라예. 한두 번이 아이고 벌씨 여러 달째라.", standard: "공성면 다리 밑입니다. 한두 번이 아니고 벌써 여러 달째입니다." },
      { role: "agent", standard: "혹시 차량이나 시간대를 기억하시는 게 있으실까요?", dialect: "혹시 차나 시간대 기억나는 기 있는교?" },
      { role: "caller", dialect: "밤 열한 시 넘어가 온다. 파란 일 톤 트럭이라.", standard: "밤 열한 시 넘어서 옵니다. 파란 1톤 트럭입니다." },
      { role: "agent", standard: "무단투기 단속 담당인 자원순환과로 접수하겠습니다.", dialect: "무단투기 단속 맡은 자원순환과로 접수하겠심더." }
    ]
  }
];
