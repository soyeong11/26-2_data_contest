"""
전력 피쳐 민감도 분석 (v2 기준, B = 용량 결측 6개 시도 제외 → 179개 지역)
---------------------------------------------------------------------------
기준(baseline): 2029년 · 용량 0.1/0.9 · 접속 0.1/0.25/0.65 · 결합 0.5/0.5 · min-max · 가중합
비교 지표: 기준 순위와의 Spearman 순위상관, 상위 10/20 유지 개수, 기준 상위 20 지역의 최대 순위 변동
입력 : 전력_시군구wide_256_개편반영_v2_20261004.csv, 전력피쳐_시군구256_개편반영_v2_20261004.csv
출력 : 민감도_요약_20261004.csv, 민감도_상위20_순위표_20261004.csv
"""
import os
import numpy as np
import pandas as pd

os.chdir(os.path.dirname(os.path.abspath(__file__)))
WIDE = "전력_시군구wide_256_개편반영_v2_20261004.csv"
FEAT = "전력피쳐_시군구256_개편반영_v2_20261004.csv"
OUT_SUM = "민감도_요약_20261004.csv"
OUT_TOP = "민감도_상위20_순위표_20261004.csv"

w = pd.read_csv(WIDE, encoding="utf-8-sig")
f = pd.read_csv(FEAT, encoding="utf-8-sig")
keep = ~f["용량데이터없음"]                       # B: 179개 지역만
w, f = w[keep.values].reset_index(drop=True), f[keep].reset_index(drop=True)
R = ["차단기229kV_여유율", "차단기154kV_여유율", "차단기345kV_여유율"]   # v2: 이미 0 절단


def norm(x, how):
    if x.max() == x.min():                        # 전 지역 동일(예: 22.9kV 2026·2027년 전부 0)
        return x * 0.0
    if how == "minmax":
        return (x - x.min()) / (x.max() - x.min())
    if how == "log_minmax":                       # 오른쪽 꼬리가 긴 MW 합계 완화
        y = np.log1p(x.clip(lower=0))
        return (y - y.min()) / (y.max() - y.min())
    if how == "rank":                             # 백분위 순위 (0~1)
        return x.rank(pct=True, method="average")
    raise ValueError(how)


def score(year=2029, wcap=(0.1, 0.9), wconn=(0.1, 0.25, 0.65), wcomb=(0.5, 0.5),
          how="minmax", combine="sum"):
    c229, c154 = w[f"전력공급229kV_{year}년_합계"], w[f"전력공급154kV_{year}년_합계"]
    cap = wcap[0] * norm(c229, how) + wcap[1] * norm(c154, how)
    conn_parts = [norm(f[r], how) if how != "minmax" else f[r] for r in R]  # 기준은 여유율 원척도
    conn = sum(a * b for a, b in zip(wconn, conn_parts))
    if combine == "sum":
        return wcomb[0] * cap + wcomb[1] * conn
    if combine == "geo":
        return np.sqrt(cap.clip(lower=0) * conn.clip(lower=0))
    if combine == "conn_only":
        return conn
    if combine == "cap_only":
        return cap
    raise ValueError(combine)


def renorm(t):
    s = sum(t)
    return tuple(x / s for x in t)


base = score()
rank_base = base.rank(ascending=False, method="min")
top10 = set(base.nlargest(10).index)
top20 = set(base.nlargest(20).index)

scen = {"기준 (2029 · 가중합 · min-max)": {}}
for y in [2026, 2027, 2028, 2030, 2031, 2032]:
    scen[f"연도: {y}년"] = dict(year=y)
for k, v in {"용량 0.08/0.92 (229 −20%)": (0.08, 0.92), "용량 0.12/0.88 (229 +20%)": (0.12, 0.88),
             "용량 0.3/0.7 (문서상 이전값)": (0.3, 0.7), "용량 0.5/0.5": (0.5, 0.5)}.items():
    scen[k] = dict(wcap=v)
for i, nm in enumerate(["22.9kV", "154kV", "345kV"]):
    for m, tag in [(0.8, "−20%"), (1.2, "+20%")]:
        t = [0.1, 0.25, 0.65]; t[i] *= m
        scen[f"접속 {nm} {tag}"] = dict(wconn=renorm(t))
scen["접속 0.2/0.3/0.5 (문서상 이전값)"] = dict(wconn=(0.2, 0.3, 0.5))
scen["결합 0.4/0.6 (접속 비중↑)"] = dict(wcomb=(0.4, 0.6))
scen["결합 0.6/0.4 (용량 비중↑)"] = dict(wcomb=(0.6, 0.4))
scen["정규화: log 후 min-max"] = dict(how="log_minmax")
scen["정규화: 백분위 순위"] = dict(how="rank")
scen["결합: 기하평균(병목)"] = dict(combine="geo")
scen["참고: 접속점수만"] = dict(combine="conn_only")
scen["참고: 용량점수만"] = dict(combine="cap_only")

rows, ranks = [], pd.DataFrame({"시군구": f["시도명"] + " " + f["시군구명"]})
for name, kw in scen.items():
    s = score(**kw)
    r = s.rank(ascending=False, method="min")
    ranks[name] = r.astype(int)
    rows.append({
        "시나리오": name,
        "Spearman": round(s.corr(base, method="spearman"), 3),
        "상위10 유지": len(top10 & set(s.nlargest(10).index)),
        "상위20 유지": len(top20 & set(s.nlargest(20).index)),
        "기준 상위20 최대 순위변동": int((r - rank_base)[list(top20)].abs().max()),
    })
# EWM은 v2 파일 값 그대로 비교
for name, col in [("EWM 가중합 (v2 파일)", "전력피쳐_EWM")]:
    s = f[col]; r = s.rank(ascending=False, method="min"); ranks[name] = r.astype(int)
    rows.append({"시나리오": name, "Spearman": round(s.corr(base, method="spearman"), 3),
                 "상위10 유지": len(top10 & set(s.nlargest(10).index)),
                 "상위20 유지": len(top20 & set(s.nlargest(20).index)),
                 "기준 상위20 최대 순위변동": int((r - rank_base)[list(top20)].abs().max())})

summary = pd.DataFrame(rows)
summary.to_csv(OUT_SUM, index=False, encoding="utf-8-sig")
top = ranks.loc[base.nlargest(20).index].reset_index(drop=True)
top.to_csv(OUT_TOP, index=False, encoding="utf-8-sig")
pd.set_option("display.width", 250)
print(summary.to_string(index=False))
