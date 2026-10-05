"""
전력 피쳐 v3 민감도 분석 (2026-10-05)
기준: v3 (2029 · 154kV/22.9kV 단일변전소 최대 MW · 0.1/0.9 · 접속 0.1/0.25/0.65 후 정규화 · 0.5/0.5 · min-max · 가중합)
대상: v3 분석대상 174개
출력: 데이터셋/민감도_요약_v3_20261005.csv, 데이터셋/민감도_상위20_순위표_v3_20261005.csv, 데이터셋/v2v3_순위비교_20261005.csv
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

os.chdir(os.path.dirname(os.path.abspath(__file__)))
W = pd.read_csv("데이터셋/전력_시군구wide_256_재집계_20261004.csv", encoding="utf-8-sig")
F = pd.read_csv("데이터셋/전력피쳐_상세_256_v3_20261005.csv", encoding="utf-8-sig")
V2 = pd.read_csv("데이터셋/전력피쳐_상세_256_20261004.csv", encoding="utf-8-sig")
ok = F["분석대상"].values
w, f, v2 = W[ok].reset_index(drop=True), F[ok].reset_index(drop=True), V2[ok].reset_index(drop=True)
R = ["차단기229kV_여유율", "차단기154kV_여유율", "차단기345kV_여유율"]


def norm(x, how):
    if x.max() == x.min():
        return x * 0.0
    if how == "minmax":
        return (x - x.min()) / (x.max() - x.min())
    if how == "log":
        y = np.log1p(x.clip(lower=0)); return (y - y.min()) / (y.max() - y.min())
    if how == "rank":
        return x.rank(pct=True)


def score(year=2029, agg="최대", wcap=(0.1, 0.9), wconn=(0.1, 0.25, 0.65), wcomb=(0.5, 0.5),
          how="minmax", conn_norm=True, combine="sum"):
    cap = wcap[0] * norm(w[f"전력공급229kV_{year}년_{agg}"], how) + wcap[1] * norm(w[f"전력공급154kV_{year}년_{agg}"], how)
    conn = sum(c * f[r] for c, r in zip(wconn, R))
    if conn_norm:
        conn = norm(conn, how)
    if combine == "geo":
        return np.sqrt(cap * conn)
    return wcomb[0] * cap + wcomb[1] * conn


base = score()
assert np.allclose(base, f["전력피쳐"]), "기준 재현 실패"
V = {"기준(v3)": base}
for s in (0.8, 1.2):
    V[f"결합 용량 비중 ×{s}"] = score(wcomb=(0.5 * s, 1 - 0.5 * s))
    a = min(0.9 * s, 1.0); V[f"154kV 비중 ×{s}"] = score(wcap=(1 - a, a))
    b = min(0.65 * s, 1.0); rest = 1 - b
    V[f"345kV 비중 ×{s}"] = score(wconn=(rest * 0.1 / 0.35, rest * 0.25 / 0.35, b))
V["22.9kV 용량 가중치 0"] = score(wcap=(0.0, 1.0))
V["용량 합계(v2 방식)"] = score(agg="합계")
V["접속 정규화 없음(v2 방식)"] = score(conn_norm=False)
for y in (2028, 2030, 2032):
    V[f"연도 {y}"] = score(year=y)
V["정규화 log"] = score(how="log")
V["정규화 백분위"] = score(how="rank")
V["기하평균(병목)"] = score(combine="geo")
V["EWM"] = f["전력피쳐_EWM"]
V["v2 전력피쳐(참고)"] = v2["전력피쳐"]

rb = base.rank(ascending=False, method="min")
top = lambda s, n: set(s.nlargest(n).index)
rows = []
for k, s in V.items():
    r = s.rank(ascending=False, method="min")
    t20 = list(top(base, 20))
    rows.append({"변형": k, "Spearman_rho": round(spearmanr(base, s)[0], 3),
                 "상위10_유지": len(top(base, 10) & top(s, 10)),
                 "상위20_유지": len(top(base, 20) & top(s, 20)),
                 "기준상위20_최대순위변동": int((r[t20] - rb[t20]).abs().max())})
summ = pd.DataFrame(rows)
summ.to_csv("데이터셋/민감도_요약_v3_20261005.csv", index=False, encoding="utf-8-sig")
print(summ.to_string(index=False))

tbl = f[["시군구코드", "시도명", "시군구명"]].copy()
for k, s in V.items():
    tbl[k] = s.rank(ascending=False, method="min").astype(int)
tbl = tbl.sort_values("기준(v3)").head(20)
tbl.to_csv("데이터셋/민감도_상위20_순위표_v3_20261005.csv", index=False, encoding="utf-8-sig")

cmp_ = f[["시군구코드", "시도명", "시군구명", "전력순위", "수용가능_1GW"]].copy()
cmp_["v2순위"] = v2["전력순위"].values
cmp_["변화(v2-v3)"] = cmp_["v2순위"] - cmp_["전력순위"]
cmp_.sort_values("전력순위").to_csv("데이터셋/v2v3_순위비교_20261005.csv", index=False, encoding="utf-8-sig")
print("\nv3 상위 15:\n", cmp_.sort_values("전력순위").head(15).to_string(index=False))
