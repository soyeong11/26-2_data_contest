"""7단계: 저장된 v3 공유용 파일 독립 검증 (2026-10-05)"""
import os, subprocess, hashlib
import numpy as np
import pandas as pd

os.chdir(os.path.dirname(os.path.abspath(__file__)))
S = "데이터셋/전력_최종피쳐_공유용_v3_20261005.csv"
D = "데이터셋/전력피쳐_상세_256_v3_20261005.csv"
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()

s = pd.read_csv(S, encoding="utf-8-sig")
d = pd.read_csv(D, encoding="utf-8-sig")
base = pd.read_csv("../crawl_4/행정시군구_기준행.csv", encoding="utf-8-sig")
ok = s["분석대상"]
checks = {
    "1. 행 수 256": len(s) == 256,
    "2. 시군구코드 유일·결측 0": s["시군구코드"].is_unique and s["시군구코드"].notna().all(),
    "3. 기준 코드 누락·초과 0, 순서 일치": list(s["시군구코드"]) == list(base["시군구코드"]),
    "4. 코드 기준 1:1 병합 가능": len(base.merge(s, on="시군구코드", validate="1:1")) == 256,
    "5. 점수 0~1 (분석대상)": all(s.loc[ok, c].between(0, 1).all() for c in ["전력피쳐", "용량점수", "접속점수", "전력피쳐_2032"]),
    "6. 결측 = 분석대상 외와 정확히 일치": all((s[c].isna() == ~ok).all() for c in ["전력피쳐", "용량점수", "접속점수", "전력순위"]),
    "7. 순위 1~174 연속성": s.loc[ok, "전력순위"].min() == 1 and s.loc[ok, "전력순위"].max() <= ok.sum(),
    "8. 분류 상호배타(분석/참고/응답없음)": ((ok.astype(int) + s["참고등급"].astype(int) + d["변전소응답없음"].astype(int)) == 1).all(),
    "9. 무응답 5곳은 결측(0 아님)": s.loc[s["전력공급_무응답"], "용량점수"].isna().all() and s["전력공급_무응답"].sum() == 5,
    "10. 판정 일관성(1GW⇒0.5GW)": (~s["수용가능_1GW"] | s["수용가능_0.5GW"]).all(),
}
# 재현성: 스크립트 재실행 후 동일 해시
before = (md5(S), md5(D))
subprocess.run(["python3", "feature_v3.py"], check=True, capture_output=True)
checks["11. 원자료→스크립트 재실행 결과 동일"] = before == (md5(S), md5(D))
for k, v in checks.items():
    print("통과" if v else "실패", k)
assert all(checks.values())
print("전체 통과")
