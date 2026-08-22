"""방언 레이어 테스트. 표준 라이브러리 unittest 만 쓴다 (pytest 의존성 없음).

    python -m unittest discover -s voisso/dialect/tests -t .

비용 규칙 (계약서 5-D)
----------------------
테스트는 **어떤 경우에도 외부 API 를 부르지 않는다.** 셸이나 ``.env`` 에
``VOISSO_DIALECT_LLM=1`` 이 있어도 여기서 끈다. 테스트 한 번이 수백 번의
API 호출이 되는 일을 막는다.
"""

import os

# import 시점에 끈다. 테스트가 to_dialect/normalize 를 수백 번 부르기 때문이다.
os.environ["VOISSO_DIALECT_LLM"] = "0"
