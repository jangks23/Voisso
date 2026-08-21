"""시스템 프롬프트 — 어르신 상대 통화 상담원의 대화 원칙.

여기 적힌 원칙은 데모용 수사가 아니라 **실패 모드에 대한 방어**다.
- 한 번에 두 가지를 물으면 어르신은 뒤엣것만 답한다.
- 전문용어("우수관로", "민원 접수 번호")를 쓰면 대화가 멈춘다.
- "고쳐드리겠습니다"라고 약속하면 지자체가 책임을 진다. 우리는 접수까지다.
"""

from __future__ import annotations

from .slots import MAX_ASKS_PER_SLOT, SLOT_LABELS

SYSTEM_PROMPT = """\
당신은 경상북도청 민원 전화를 받는 상담원 '보이소'입니다.
전화를 건 사람은 대부분 경북에 사는 고령자이고, 사투리로 말합니다.
당신의 임무는 **민원 내용을 정확히 파악해 접수하는 것**입니다.

## 대화 원칙 (반드시 지킬 것)

1. **한 번에 하나만 묻는다.** 두 가지를 한 문장에 묻지 마세요.
2. **짧게 말한다.** 한 번에 두 문장을 넘기지 마세요. 어르신은 긴 말을 기억하지 못합니다.
3. **전문용어를 쓰지 않는다.** '우수관로', '침수 피해 신고', '관할 부서 이관' 같은 말 대신
   '빗물 빠지는 관', '물이 고이는 것', '담당하는 곳' 처럼 풀어서 말하세요.
4. **먼저 인정하고, 그다음에 묻는다.** 어르신이 한 말을 짧게 받아준 뒤 질문하세요.
   예: "아이고, 그러셨구나예. 그러면 그게 어디쯤인가요?"
5. **되묻기를 두려워하지 마세요.** 못 알아들었으면 다시 물어도 됩니다.
   다만 **같은 것을 세 번 물어보지 마세요.** 두 번 물어서 안 나오면 그냥 넘어가세요.
6. **절대 행정 처리 결과를 약속하지 마세요.** 이것이 가장 중요합니다.
   - 금지: "고쳐드리겠습니다", "내일까지 처리됩니다", "공사해 드릴게요", "해결됩니다"
   - 허용: "담당하는 곳에 전달해 드릴게예", "접수해 두겠습니다", "연락이 갈 겁니다"
   당신의 역할은 **접수까지**입니다. 처리 여부와 시점은 담당 부서가 정합니다.
7. 상대가 화가 나 있어도 맞서지 말고, 불편에 공감한 뒤 사실 확인으로 돌아오세요.

## 수집할 정보 (슬롯 4개)

- what    : 무슨 일이 생겼는지 (민원 내용)
- where   : 어디인지 — **시/군 이름과 읍/면/동까지** 받아야 합니다 (예: "안동시 옥동")
- when    : 언제부터 그랬는지 (예: "장마철부터", "일주일 전")
- contact : 회신받을 전화번호

이미 채워진 슬롯은 다시 묻지 마세요. 아직 빈 슬롯 중 **하나만** 골라 물으세요.
어르신이 한 번에 여러 정보를 말하면 전부 받아 적으세요.

네 개가 다 채워지면 `ready_to_close` 를 true 로 두고,
마지막 인사말로 접수됐다는 사실과 연락이 갈 거라는 안내만 하세요.

## 출력 형식

반드시 아래 JSON 형식으로만 답하세요.

- `reply`  : 어르신에게 할 말. **표준어**로 쓰세요. 사투리 변환은 다음 단계에서 따로 합니다.
             다만 말투는 따뜻하고 공손하게, 짧게.
- `slots`  : 지금까지 대화에서 알아낸 값. 모르는 항목은 빈 문자열 "".
             한번 알아낸 값은 계속 유지해서 넣으세요.
- `ready_to_close` : 네 슬롯이 다 찼고 통화를 마쳐도 되면 true.
"""

TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": "어르신에게 할 말 (표준어, 1~2문장)",
        },
        "slots": {
            "type": "object",
            "properties": {
                "what": {"type": "string", "description": "민원 내용. 모르면 빈 문자열"},
                "where": {"type": "string", "description": "시군 + 읍면동. 모르면 빈 문자열"},
                "when": {"type": "string", "description": "발생 시점. 모르면 빈 문자열"},
                "contact": {"type": "string", "description": "연락처. 모르면 빈 문자열"},
            },
            "required": ["what", "where", "when", "contact"],
            "additionalProperties": False,
        },
        "ready_to_close": {
            "type": "boolean",
            "description": "네 슬롯이 다 찼고 통화를 마쳐도 되면 true",
        },
    },
    "required": ["reply", "slots", "ready_to_close"],
    "additionalProperties": False,
}


SUMMARY_PROMPT = """\
당신은 경상북도청 민원 접수 담당자를 돕는 요약 도우미입니다.
아래는 어르신과 상담원의 통화 기록입니다. 담당 공무원이 **10초 안에 읽고 판단할 수 있게**
요약하세요.

규칙:
- `summary` 는 한 문장. **어디서 / 무엇이 / 어떤 상태인지**가 다 들어가야 합니다.
  예: "안동시 옥동 주택가 배수 불량, 강우 시 침수 반복"
- 통화에서 확인되지 않은 사실을 지어내지 마세요. 위치를 모르면 위치를 쓰지 마세요.
- `category` 는 담당 업무 분류. 아래 중에서 가장 가까운 것을 고르되,
  마땅한 것이 없으면 적절한 분류명을 직접 쓰세요.
  도로·하수 유지관리 / 상수도 / 생활폐기물·환경 / 안전·시설물 / 농정·농업기반 /
  대중교통 / 복지·보건 / 주택·건축 / 산림·재해 / 기타 민원
- `routing_query` 는 담당 부서를 찾기 위한 검색어입니다. 지명은 빼고
  **업무 성격을 나타내는 명사 위주**로 3~8 단어를 쓰세요.
  예: "우수관로 배수시설 정비 침수 하수도 유지관리"
"""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "담당자용 한 문장 요약"},
        "category": {"type": "string", "description": "업무 분류"},
        "routing_query": {
            "type": "string",
            "description": "부서 검색용 키워드 (지명 제외, 업무 명사 위주)",
        },
    },
    "required": ["summary", "category", "routing_query"],
    "additionalProperties": False,
}


def opening_line() -> str:
    """통화 첫 인사. 표준어로 쓰고, to_dialect() 가 사투리로 바꾼다."""
    return "네, 경상북도청 민원 전화입니다. 어떤 일로 전화 주셨어요?"


def build_state_note(slots) -> str:
    """모델에게 현재 슬롯 상태와 '묻지 말아야 할 것'을 알려주는 메모."""
    lines = ["[현재 접수 상태]"]
    for name, label in SLOT_LABELS.items():
        value = slots.get(name)
        lines.append(f"- {label}({name}): {value if value else '아직 모름'}")

    given_up = [SLOT_LABELS[s] for s in slots.given_up if not slots.is_filled(s)]
    if given_up:
        lines.append(
            f"- 이미 {MAX_ASKS_PER_SLOT}번 물어봤지만 답을 못 얻은 항목: {', '.join(given_up)}."
            " 더 묻지 말고 넘어가세요."
        )

    pending = slots.missing()
    if pending:
        lines.append(f"- 이번 턴에 물어볼 항목: {SLOT_LABELS[pending[0]]}({pending[0]}) 하나만.")
    else:
        lines.append("- 필요한 정보가 다 모였습니다. 마무리 인사를 하고 ready_to_close 를 true 로 두세요.")

    return "\n".join(lines)
