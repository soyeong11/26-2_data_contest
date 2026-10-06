"""
전력 피쳐 v4 민감도 분석 (2026-10-06)
=====================================
기준: feature_v4.py의 B안 (2029년, 용량MW = max(22.9kV, 154kV) → min-max)
비교안
  [전압 가중치] A. 0:10 (154kV 단독) / 1:9 (기존 v3) / 3:7  — 각 전압을 min-max한 뒤 가중합 (v3 방식)
  [기준연도]    B안 그대로 2028 / 2030 / 2032
지표
  순위상관(Spearman, 분석대상 전체) · 상위10 겹침 · 상위20 겹침 · 상위20 진입/이탈 지역
  상위 N은 동점을 포함하지 않도록 '순위 ≤ N'이 아니라 점수 상위 N개(동점은 시군구코드 순)로 자름

해석 기준 (용량점수 vs 접속점수 채팅에서 정한 것)
  순위가 거의 그대로면 '가중치 선택이 결과를 좌우하지 않는다'는 근거,
  크게 바뀌면 그 지역들을 따로 논의

출력  데이터셋/민감도_요약_v4_{날짜}.csv, 데이터셋/민감도_상위20_순위표_v4_{날짜}.csv
"""
import os
import pandas as pd
import feature_v4 as fv

OUT_SUM = os.path.join(fv.DATA, f"민감도_요약_v4_{fv.TAG}.csv")
OUT_TOP = os.path.join(fv.DATA, f"민감도_상위20_순위표_v4_{fv.TAG}.csv")


def weighted(w, ok, year, w229):
    v229, v154 = w[f"전력공급229kV_{year}년_최대"], w[f"전력공급154kV_{year}년_최대"]
    return w229 * fv.minmax(v229, ok) + (1 - w229) * fv.minmax(v154, ok)


def b_score(w, ok, year):
    return fv.minmax(fv.capacity_mw(w, year)[0], ok)


def top_n(s, codes, n):
    d = pd.DataFrame({"s": s, "c": codes}).dropna().sort_values(["s", "c"], ascending=[False, True])
    return set(d.index[:n])


def main():
    w, c = fv.load()
    ok = c["분류"].eq("분석대상")
    codes = w["지역코드"]
    base = b_score(w, ok, fv.BASE_YEAR)
    variants = {
        "A. 154kV 단독 (0:10)": weighted(w, ok, fv.BASE_YEAR, 0.0),
        "1:9 (기존 v3)": weighted(w, ok, fv.BASE_YEAR, 0.1),
        "3:7": weighted(w, ok, fv.BASE_YEAR, 0.3),
        "B안 2028": b_score(w, ok, 2028),
        "B안 2030": b_score(w, ok, 2030),
        "B안 2032": b_score(w, ok, 2032),
    }
    b10, b20 = top_n(base, codes, 10), top_n(base, codes, 20)
    name = w["시군구명"]
    dup = name.duplicated(keep=False)                 # 동구·중구처럼 겹치는 이름은 시도명을 붙임
    name = name.where(~dup, w["시도명"] + " " + name)
    rows = []
    for k, s in variants.items():
        t10, t20 = top_n(s, codes, 10), top_n(s, codes, 20)
        rows.append({
            "비교안": k,
            "순위상관": round(s[ok].rank().corr(base[ok].rank()), 3),
            "상위10겹침": len(t10 & b10), "상위20겹침": len(t20 & b20),
            "상위20_진입": ", ".join(name[sorted(t20 - b20)]),
            "상위20_이탈": ", ".join(name[sorted(b20 - t20)]),
        })
    summ = pd.DataFrame(rows)
    summ.to_csv(OUT_SUM, index=False, encoding="utf-8-sig")

    # 어느 안에서든 상위20에 든 지역의 안별 순위
    union = set(b20).union(*[top_n(s, codes, 20) for s in variants.values()])
    tab = pd.DataFrame({"시군구코드": codes, "시도명": w["시도명"], "시군구명": name,
                        "B안 2029 (기준)": fv.rank_desc(base, ok)})
    for k, s in variants.items():
        tab[k] = fv.rank_desc(s, ok)
    tab = tab.loc[sorted(union)].sort_values(["B안 2029 (기준)", "시군구코드"])
    tab.to_csv(OUT_TOP, index=False, encoding="utf-8-sig")

    print(f"\n[민감도] 기준 = B안 {fv.BASE_YEAR}, 분석대상 {int(ok.sum())}곳")
    print(summ[["비교안", "순위상관", "상위10겹침", "상위20겹침"]].to_string(index=False))
    for r in rows:
        if r["상위20_진입"]:
            print(f"  {r['비교안']}: 진입 [{r['상위20_진입']}] / 이탈 [{r['상위20_이탈']}]")
    print("저장:", os.path.basename(OUT_SUM), os.path.basename(OUT_TOP))


if __name__ == "__main__":
    main()