# CHALLENGE_GOAL

> 이 문서는 본 프로젝트가 반드시 달성해야 하는 **목표와 제약조건, 채점 기준**을 정의한다.
> 모든 설계·구현·문서 작업은 이 문서를 기준으로 판단한다. 충돌이 생기면 이 문서가 우선한다.

---

## Challenge

**Solve local challenges in Gyeongsangbuk-do using public data.**
*by JunctionX Korea*

### The Challenge

Building Open-Source Data Infrastructure: Rediscovering Gyeongsangbuk-do's Public Data for the AI Era.

Korea's public data portal opens more than 100,000 datasets via API. The country has also ranked first in the OECD's public data assessment four times running. Yet shaping that data so AI can use it right away, and putting it to work on real problems, is still left to individual effort.

Participants pick one or both of two directions:

1. **Infrastructure track** — process and publish Gyeongsangbuk-do-related public data in a form AI can use through standard means, such as an **MCP server** or **open-source skills and plugins**.
2. **Service track** — use open data and AI to find and analyze regional issues in Gyeongsangbuk-do and build a service that solves them.

**Every team must use at least one public dataset.**

Those taking the infrastructure route must:
- publish on **GitHub** under a **clearly stated open-source license**, and
- the project **must run from the README alone**, with **no prior knowledge required**.

Outstanding projects may be transferred to a repository under the **Gyeongsangbuk-do Provincial Government** name and kept in operation.

### Insight

*Share the differentiating insight that inspired this challenge.* (주최측 원문에 구체적 내용 미기재 — 제출 시 우리 팀의 차별화 인사이트를 여기에 서술한다.)

### Company Info

JunctionX Korea

---

## Judging Criteria (채점 기준)

| 항목 | 배점 | 원문 |
|---|---|---|
| 기술적 완성도 | **25%** | Technical Completeness |
| 공공부문 활용 가능성 | **25%** | Potential for Public-Sector Use |
| 혁신성 및 차별성 | **20%** | Innovation & Differentiation |
| 지속가능성 및 임팩트 | **20%** | Sustainability & Impact |
| 프로토타입 보너스 | **10%** | Prototype Bonus |

**Prizes:** To be announced

---

## 필수 준수사항 (Hard Requirements)

이것들은 선택이 아니라 **탈락 조건**이다. 모든 작업은 아래를 위반하지 않아야 한다.

- [ ] **공공데이터를 최소 1개 이상 실제로 사용**한다. (mock/더미 데이터만으로 끝내지 않는다.)
- [ ] 데이터는 **경상북도(Gyeongsangbuk-do)와 관련**되어야 한다.
- [ ] **인프라 트랙을 택할 경우:**
  - [ ] GitHub에 **공개** 저장소로 게시한다.
  - [ ] **오픈소스 라이선스를 명시**한다. (`LICENSE` 파일 필수)
  - [ ] **README만 보고 처음 보는 사람이 실행할 수 있어야 한다.** 사전 지식 요구 금지.
  - [ ] AI가 **표준적인 방법**으로 소비할 수 있는 형태로 제공한다 (MCP 서버 / 오픈소스 skill / plugin 등).
- [ ] **서비스 트랙을 택할 경우:**
  - [ ] 경상북도의 **실제 지역 문제**를 공공데이터로 발굴·분석한다.
  - [ ] 그 문제를 해결하는 **동작하는 서비스**를 만든다.
- [ ] 경상북도청 명의 저장소로 **이관되어 계속 운영될 수 있는 수준**의 코드/문서 품질을 유지한다.

## 채점 기준에 대응하는 작업 원칙

- **기술적 완성도 (25%)** — 데모용 껍데기가 아니라 실제로 동작해야 한다. 에러 핸들링, 재현 가능한 실행, 테스트를 갖춘다.
- **공공부문 활용 가능성 (25%)** — 지자체 담당자가 그대로 쓸 수 있는가를 항상 자문한다. 특정 개인 환경에 의존하지 않게 만든다.
- **혁신성 및 차별성 (20%)** — 이미 있는 포털 조회 기능의 재탕이 아니어야 한다. "AI가 바로 쓸 수 있는 형태"라는 지점이 차별점이다.
- **지속가능성 및 임팩트 (20%)** — 해커톤 이후에도 유지될 수 있게 만든다. 데이터 갱신 경로, 문서, 라이선스, 기여 가이드를 갖춘다.
- **프로토타입 보너스 (10%)** — 반드시 **눈으로 볼 수 있는 동작하는 프로토타입**을 확보한다.
