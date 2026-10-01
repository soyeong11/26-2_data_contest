"""
크롤링 결과 점검 스크립트 (읽기 전용 — 어떤 파일도 수정하지 않음)
사용:  python check_output.py            (이 파일과 같은 폴더의 '데이터셋/' 을 검사)
       python check_output.py 경로        (다른 폴더 지정)
출력 전체를 복사해서 붙여넣으면 됩니다.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kepco_crawler import korean_colname  # noqa: E402

D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "데이터셋")
NAMES = {"sup229": "전력공급_여유용량_22.9kV.csv", "sup154": "전력공급_여유용량_154kV.csv",
         "renw": "재생e_연계_여유용량.csv", "cbr": "차단기_여유Bay_22.9_154kV.csv",
         "c345": "차단기_여유Bay_345kV.csv"}
CODES = {c: str for c in ["시도코드", "시군구코드", "읍면동코드", "변전소관리번호", "변전소코드"]}


def rd(fname, **kw):
    p = os.path.join(D, fname)
    if not os.path.exists(p):
        print(f"  (없음: {fname})")
        return None
    return pd.read_csv(p, encoding="utf-8-sig", **kw)


def sec(t):
    print(f"\n──── {t}")


def flag(ok, msg_ok, msg_bad):
    print(("  [OK] " + msg_ok) if ok else ("  [확인 필요] " + msg_bad))


print(f"검사 폴더: {D}")
raw = {k: rd(v, dtype=CODES) for k, v in NAMES.items()}
master = rd("지역마스터_시군구.csv", dtype=str, keep_default_na=False)
sgg = rd("지역별_시군구_wide.csv", dtype={"시도코드": str, "시군구코드": str, "지역코드": str}, keep_default_na=False)
sido = rd("지역별_시도_wide.csv", dtype={"시도코드": str}, keep_default_na=False)

# 1) 지역코드: 데이터에 있는데 마스터에 없는 코드 -----------------------------
sec("1. 지역코드 불일치 (데이터에는 있는데 지역마스터에 없는 시군구 코드)")
if master is not None:
    valid = set(zip(master.sido_cd, master.sgg_cd))
    tot = 0
    for k in ("sup229", "sup154", "renw", "cbr"):
        df = raw[k]
        if df is None:
            continue
        g = df.drop_duplicates(["시도코드", "시군구코드"])
        miss = g[[(a, b) not in valid for a, b in zip(g["시도코드"], g["시군구코드"])]]
        tot += len(miss)
        for r in miss.itertuples():
            print(f"  {k}: {r.시도코드}-{r.시군구코드}  {r.시도} {r.시군구}")
    flag(tot == 0, "모든 코드가 마스터에 있음", f"마스터에 없는 코드 {tot}건 (시군구 wide 행이 마스터 수보다 늘어난 원인)")
    if sgg is not None:
        print(f"  참고: 마스터 시군구 {int((master.sgg_cd != '').sum())}개 / 시군구 wide {len(sgg)}행")

# 2) 22.9kV 와 154kV 가 정말 다른 값인가 ---------------------------------------
sec("2. 전력공급 22.9kV vs 154kV — 값이 실제로 다른지")
a, b = raw["sup229"], raw["sup154"]
if a is not None and b is not None:
    key = ["시도코드", "시군구코드", "읍면동코드", "변전소관리번호", "변전소"]
    yc = [c for c in a.columns if c.startswith("여유용량_")] + ["최소여유용량"]
    m = a.merge(b, on=key, suffixes=("_a", "_b"))
    same = (m[[c + "_a" for c in yc]].fillna(-1).values == m[[c + "_b" for c in yc]].fillna(-1).values).all(axis=1)
    print(f"  행 {len(a)} / {len(b)}, 키 일치 {len(m)}행, 값까지 완전 동일 {int(same.sum())}행")
    flag(same.mean() < 0.95 if len(m) else False, "대부분 값이 서로 다름 (정상)",
         "거의 전부 동일 — 두 요청이 같은 데이터를 돌려주는 것일 수 있음")

# 3) 제주 ------------------------------------------------------------------------
sec("3. 제주 데이터 유무")
if master is not None:
    jj = master.loc[master.sido_nm.str.contains("제주"), "sido_cd"]
    jc = jj.iloc[0] if len(jj) else "50"
    for k, df in raw.items():
        if df is not None and "시도코드" in df.columns:
            print(f"  {k}: 제주 {int((df['시도코드'] == jc).sum())}행")
    print("  -> 전력공급/재생e가 0행이면 wide 표의 제주 sup*/renw* 0은 '없음'이 아니라 '미수집'")

# 4) 차단기(22.9/154kV) -----------------------------------------------------------
sec("4. 차단기(22.9/154kV) — 중복·항등식")
c = raw["cbr"]
if c is not None:
    k = ["시도코드", "시군구코드", "읍면동코드", "변전소코드"]
    d = c.duplicated(k, keep=False)
    flag(not d.any(), "코드 기준 중복 없음", f"같은 (지역코드+변전소코드) 행이 {int(d.sum())}개 — 상위 시(부천시/화성시 등)와 하위 구 조회가 겹쳤을 수 있음")
    multi = c.groupby("변전소코드")["시군구코드"].nunique()
    print(f"  한 변전소가 여러 시군구에 나오는 경우: {int((multi > 1).sum())}개")
    for v in ("22.9kV", "154kV"):
        diff = c[f"차단기_{v}_전체대수"] - c[f"차단기_{v}_사용중"] - c[f"차단기_{v}_사용예정"] - c[f"차단기_{v}_여유대수"]
        bad = c[diff.fillna(0) != 0]
        flag(len(bad) == 0, f"{v}: 전체 = 사용중 + 사용예정 + 여유 성립", f"{v}: 항등식 어긋난 행 {len(bad)}개")
        for r in bad.head(5).itertuples():
            print(f"     예) {r.시도} {r.시군구} {r.변전소}")

# 5) 345kV ---------------------------------------------------------------------------
sec("5. 345kV — 매핑·항등식")
t = raw["c345"]
um = rd("345kV_지역매핑_미매칭.csv")
mp = rd("345kV_공급지역_매핑.csv")
if um is not None:
    print(f"  미매칭 토큰 {len(um)}건" + (":" if len(um) else ""))
    if len(um):
        print(um.head(40).to_string(index=False))
if t is not None and mp is not None:
    none_mapped = sorted(set(t["변전소"]) - set(mp["변전소"]))
    print(f"  지역이 하나도 안 잡힌 변전소: {none_mapped}")
if t is not None:
    for v, cols in (("345kV", ["최종", "사용중", "사용예정", "잔여"]), ("154kV", ["최종", "사용중", "사용예정", "잔여"])):
        f = [f"차단기_{v}_{x}" for x in cols]
        diff = t[f[0]] - t[f[1]] - t[f[2]] - t[f[3]]
        bad = t[diff.fillna(0) != 0]
        flag(len(bad) == 0, f"{v}: 최종 - 사용중 - 사용예정 = 잔여 성립", f"{v}: 항등식 어긋난 행 {len(bad)}개: {bad['변전소'].tolist()[:8]}")
        neg = t[t[f[3]] < 0]
        if len(neg):
            print(f"  참고: {v} 잔여가 음수인 변전소 {neg['변전소'].tolist()} (합계 컬럼에 음수가 섞임)")
    print(f"  공급가능지역이 빈 변전소: {t.loc[t['공급가능지역'].isna(), '변전소'].tolist()}")

# 6) 데이터가 전혀 없는 시군구 --------------------------------------------------------------
sec("6. 모든 블록이 0인 시군구")
if sgg is not None:
    nc = [c for c in sgg.columns if c.endswith("_변전소수")]
    z = sgg[(sgg[nc] == 0).all(axis=1)]
    print(f"  {len(z)}개 / 전체 {len(sgg)}개")
    if len(z):
        print("  " + ", ".join((z["시도명"] + " " + z["시군구명"]).head(40)))

# 7) 원본 합계 = wide 합계 ----------------------------------------------------------------------
sec("7. 원본 합계 vs wide(시도) 합계")
if sido is not None:
    for blk, col_raw, col_w in (("sup229", "여유용량_2026", korean_colname("sup229_y2026_sum")),
                                ("sup154", "여유용량_2026", korean_colname("sup154_y2026_sum")),
                                ("renw", "여유용량_2026", korean_colname("renw_y2026_sum")),
                                ("cbr", "차단기_154kV_여유대수", korean_colname("cbr_b154_futu_sum"))):
        df = raw[blk]
        if df is None or col_w not in sido.columns:
            continue
        r, w = pd.to_numeric(df[col_raw], errors="coerce").sum(), pd.to_numeric(sido[col_w]).sum()
        flag(abs(r - w) < 1e-6, f"{blk}: {r:g} == {w:g}", f"{blk}: 원본 {r:g} != wide {w:g}")