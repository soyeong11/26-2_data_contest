"""
2단계: KEPCO 크롤링 원본 → 팀 256 시군구(기준_시군구256.csv) 재배정 후 wide 재집계
=====================================================================================
final/feature_reorg.py(10-04 A단계)의 재배정 규칙을 그대로 따르되, 읍면동 wide 대신
'변전소 단위 원본'에서 재배정·재집계한다.
  - 읍면동 wide는 크롤러의 (시도,시군구,관리번호) 중복제거 때문에 일부 읍면동 행이 빠져 있어,
    읍면동 wide를 합치면 합계/변전소수가 틀어질 수 있음
  - 원본에서 변전소마다 256 기준 코드를 붙이고, 크롤러의 집계 함수(build_level)를 그대로 돌림
    → 출력 컬럼은 지역별_시군구_wide.csv와 동일 + feature_v3.py가 쓰는 플래그 2개
       (345kV_상위지역공유, 변전소응답없음)

실행 (final_v4 폴더, kepco_crawler.py와 같은 폴더)
  python step2_시군구.py            매핑에 없는 읍면동이 있으면 추가할 목록만 저장하고 중단
  python step2_시군구.py --force    매핑에 없는 행은 빼고 강행 (권장 X, 빠진 행은 내역 파일에 기록)

입력
  데이터셋/ (크롤러 산출물)  원본 CSV 5종 + 지역마스터_시군구.csv
  데이터셋/기준_시군구256.csv        시군구코드(5자리), 개편전코드, 시도명, 시군구 ...  (256행)
  개편매핑_법정동.csv                개편전코드, 읍면동명, 신코드 (+신시군구명, 근거)
                                     데이터셋/ 에 없으면 ../final/데이터셋/ 에서 찾음
                                     신코드에 '제외'를 쓰면 그 읍면동 행은 의도적으로 뺌 (예: 소속 불명 읍면동)

재배정 규칙 (코드 기준 — KEPCO 코드가 기준표 코드와 같은 체계임을 확인함, 2026-10-06 크롤링)
  1) KEPCO 5자리 코드(시도+시군구)가 기준표에 있으면 그대로
  2) 기준표 '개편전코드'에 있으면 새 코드로 (예: 47720 경북 군위군 → 27720 대구 군위군)
  3) 개편매핑의 개편전코드(화성시·부천시·인천 중구/동구/서구)면 (개편전코드, 읍면동명) → 신코드
  4) 그 외는 미배정 (내역 파일에 기록)
  차단기 원본에는 읍면동명이 없어 같은 (코드,읍면동코드)의 이름을 재생e→전력공급 원본에서 가져옴.
  KEPCO 읍면동코드는 이름과 1:1이 아니어서(같은 코드에 두 이름), 후보 이름들이 서로 다른 신코드로
  가면 '읍면동코드 모호'로 미배정 처리함.

중복 처리
  - 재배정으로 같은 신 시군구에 '같은 변전소'가 원래코드만 다르게 두 번 들어가면 1행만 남김
    (전력공급/재생e: 변전소관리번호, 차단기: 변전소코드+Bay 8개 값 일치) — 10-04의 새솔동 수동 제거를 일반화
  - 서로 다른 시군구에 같은 변전소가 나오는 것은 KEPCO가 공급 변전소 기준으로 응답하는 것이라 정상 → 유지
  - 345kV는 공급가능지역 텍스트가 상위 시 단위('화성시')라 신설구 전체에 복제, 345kV_상위지역공유=True

출력 (데이터셋/)
  전력_시군구wide_256_재집계_{날짜}.csv   256행, 기준표 순서 → feature 코드 입력
  개편재배정_내역_{날짜}.csv             재배정·중복제거·미배정 행 전부
  개편매핑_추가필요_{날짜}.csv           매핑에 없는 읍면동 (신코드 채워서 개편매핑_법정동.csv에 추가)
"""
import os
import sys
from datetime import datetime
import pandas as pd
import kepco_crawler as kc

TAG = datetime.now().strftime("%Y%m%d")
F_STD = "기준_시군구256.csv"
F_MAP = "개편매핑_법정동.csv"
MAP_CANDIDATES = [os.path.join(kc.SAVE_DIR, F_MAP),
                  os.path.join(os.path.dirname(kc.SAVE_DIR), "..", "final", "데이터셋", F_MAP)]
F_OUT = f"전력_시군구wide_256_재집계_{TAG}.csv"
F_LOG = f"개편재배정_내역_{TAG}.csv"
F_TODO = f"개편매핑_추가필요_{TAG}.csv"

# 분석에서 뺄 (개편전코드, 읍면동명) — 개편매핑_법정동.csv보다 우선 적용됨 (2026-10-06 결정)
EXCLUDE_EMD = {
    ("28140", "숭의동"): "인천 동구 조회 응답이나 숭의동은 미추홀구 소재 — 매핑 불가, 분석 제외",
    ("28260", "금곡동"): "인천 서구 조회 응답 — 매핑 불가, 분석 제외",
    ("41190", "부개동"): "부천시 조회 응답이나 부개동은 인천 부평구 소재(부평구 자체 응답에 같은 변전소 있음) — 분석 제외",
}

ENERGY = ("sup229", "sup154", "renw")
SITE_BLOCKS = ("sup229", "sup154", "renw", "cbr")      # 변전소 소재지 기준 블록 (345kV 제외)
BAY_COLS = list(kc.CBR_MAP)


def nm_key(x):
    return "" if pd.isna(x) else str(x).replace(" ", "").strip()


def read_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


# ── 기준표 · 매핑 ────────────────────────────────────────────
def load_std():
    p = os.path.join(kc.SAVE_DIR, F_STD)
    if not os.path.exists(p):
        sys.exit(f"!! 기준표 없음: {p}")
    s = read_csv(p)
    s["code"] = s["시군구코드"].str.strip().str.zfill(5)
    s["old"] = s["개편전코드"].str.strip()
    if s["code"].duplicated().any():
        sys.exit(f"!! 기준표 시군구코드 중복: {s.loc[s['code'].duplicated(), 'code'].tolist()}")
    print(f"  기준표: {len(s)}행")
    return s


def load_map(std):
    p = next((c for c in MAP_CANDIDATES if os.path.exists(c)), None)
    if p is None:
        sys.exit(f"!! {F_MAP} 없음 (찾은 위치: {MAP_CANDIDATES})")
    m = read_csv(p)
    # 코드에 적은 제외 목록을 덧붙이고, 같은 (개편전코드, 읍면동명)이 파일에 있으면 제외 쪽을 남김
    ex = pd.DataFrame([{"개편전코드": o, "읍면동명": e, "신코드": "제외", "신시군구명": "", "근거": why}
                       for (o, e), why in EXCLUDE_EMD.items()])
    m = pd.concat([m, ex], ignore_index=True)
    m = m[~m.assign(_k=m["읍면동명"].map(nm_key)).duplicated(["개편전코드", "_k"], keep="last")]
    m["old"], m["new"] = m["개편전코드"].str.strip(), m["신코드"].str.strip()
    m = m[m["new"] != ""]
    bad = set(m["new"]) - set(std["code"]) - {"제외"}
    if bad:
        sys.exit(f"!! {F_MAP}의 신코드가 기준표에 없음: {sorted(bad)}")
    m["k"] = m["읍면동명"].map(nm_key)
    clash = m.groupby(["old", "k"])["new"].nunique()
    if (clash > 1).any():
        sys.exit(f"!! {F_MAP}에서 같은 (개편전코드, 읍면동명)이 서로 다른 신코드로 감: {clash[clash > 1].index.tolist()}")
    print(f"  개편매핑: {os.path.abspath(p)}  ({len(m)}행 = 파일 + 코드 내 제외 {len(EXCLUDE_EMD)}개, "
          f"개편전코드 {m['old'].nunique()}개)")
    return m


class Resolver:
    def __init__(self, std, mp):
        self.codes = set(std["code"])
        self.renamed = {o: c for o, c in zip(std["old"], std["code"]) if o and o not in self.codes}
        self.lut = {(o, k): n for o, k, n in zip(mp["old"], mp["k"], mp["new"])}
        real = mp[mp["new"] != "제외"]
        self.children = real.groupby("old")["new"].apply(lambda x: sorted(set(x))).to_dict()
        for o in set(mp["old"]) - set(self.children):      # 제외만 있는 개편전코드도 '쪼개진 코드'로 인식
            self.children[o] = []

    def resolve(self, c5, emd_names):
        """emd_names: 후보 읍면동명 목록 (전력공급·재생e는 1개, 차단기는 코드 사전에서 0~여러 개)"""
        if c5 in self.codes:
            return c5, "그대로"
        if c5 in self.renamed:
            return self.renamed[c5], "코드변경"
        if c5 in self.children:
            hits = {self.lut.get((c5, nm_key(e))) for e in emd_names if nm_key(e)}
            if not emd_names or not any(nm_key(e) for e in emd_names):
                return None, "미배정(읍면동명 없음)"
            if None in hits:
                return None, "미배정(매핑에 없는 읍면동)"
            if len(hits) > 1:
                return None, "미배정(읍면동코드 모호)"
            h = hits.pop()
            return (None, "제외(매핑표 지정)") if h == "제외" else (h, "재배정")
        return None, "미배정(기준표에 없는 코드)"

    def resolve_all(self, c5):
        """345kV: (신코드 목록, 상위지역 복제 여부)"""
        if c5 in self.codes:
            return [c5], False
        if c5 in self.renamed:
            return [self.renamed[c5]], False
        if c5 in self.children:
            return self.children[c5], True
        return [], False


# ── 원본 → 정규화 (변전소 식별자 유지) ────────────────────────
def load_blocks():
    raws = {"sup229": kc.read_raw(kc.F_SUP229), "sup154": kc.read_raw(kc.F_SUP154),
            "renw": kc.read_raw(kc.F_RENW), "cbr": kc.read_raw(kc.F_CBR), "c345": kc.read_raw(kc.F_C345)}
    for k, v in raws.items():
        print(f"  {k}: {'없음' if v is None else f'{len(v)}행'}")
    norm = {}
    for p in ENERGY:
        raw = raws[p]
        if raw is None:
            continue
        ycols = [f"여유용량_{y}" for y in kc.YEARS]
        keep = raw[ycols].apply(pd.to_numeric, errors="coerce").notna().any(axis=1)   # norm_energy의 dropna와 동일
        df = kc.norm_energy(raw, renewable=(p == "renw"))
        assert len(df) == int(keep.sum())
        df["sub_id"] = raw.loc[keep, "변전소관리번호"].fillna("").astype(str).str.strip().values
        df["sub_nm"] = raw.loc[keep, "변전소"].fillna("").values
        norm[p] = (df, kc.R_METRICS if p == "renw" else kc.E_METRICS)
    if raws["cbr"] is not None:
        df = kc.norm_cbr(raws["cbr"])
        df["sub_id"] = raws["cbr"]["변전소코드"].fillna("").astype(str).str.strip().values
        df["sub_nm"] = raws["cbr"]["변전소"].fillna("").values
        norm["cbr"] = (df, BAY_COLS)
    if not norm:
        sys.exit("!! 원본 CSV가 없습니다. 크롤링 먼저.")
    return raws, norm


def emd_name_lookup(norm):
    """(5자리코드+읍면동코드) → 읍면동명 후보 집합. 재생e(차단기와 같은 cpct 네임스페이스) 우선, 없으면 전력공급"""
    out = {}
    for p in ("renw", "sup154", "sup229"):          # 앞선 출처에 있는 코드는 뒤 출처로 덮지 않음
        if p not in norm:
            continue
        df = norm[p][0]
        src = {}
        for c, n in zip(df["sido_cd"] + df["sgg_cd"] + df["emd_cd"], df["emd_nm"]):
            if nm_key(n):
                src.setdefault(c, set()).add(n)
        for c, names in src.items():
            out.setdefault(c, names)
    return out


# ── 재배정 ───────────────────────────────────────────────────
def remap_block(p, df, res, std, lookup):
    df = df.copy()
    df["원래코드"] = df["sido_cd"] + df["sgg_cd"]
    if p == "cbr":
        cands = [sorted(lookup.get(c + e, ())) for c, e in zip(df["원래코드"], df["emd_cd"])]
    else:
        cands = [[n] for n in df["emd_nm"]]
    r = [res.resolve(c, n) for c, n in zip(df["원래코드"], cands)]
    df["신코드"] = [x[0] for x in r]
    df["처리"] = [x[1] for x in r]
    df["읍면동명_사용"] = [" / ".join(n) for n in cands]

    ok = df["신코드"].notna()
    # 재배정으로 생긴 같은 시군구 내 중복 (원래코드가 다른 같은 변전소)
    dup = pd.Series(False, index=df.index)
    has_id = ok & df["sub_id"].ne("") & df["sub_id"].ne("nan")
    key_cols = ["신코드", "sub_id"] + (BAY_COLS if p == "cbr" else [])
    sub = df[has_id]
    if len(sub):
        kk = sub[key_cols].astype(str).agg("|".join, axis=1)
        multi = sub.groupby(kk)["원래코드"].transform("nunique") > 1
        # 원래 그 구의 행('그대로')을 남기고 상위 시에서 재배정된 행을 지움
        order = sub.assign(_k=kk, _p=(sub["처리"] != "그대로").astype(int)).sort_values(["_k", "_p"], kind="stable")
        first = pd.Series(~order["_k"].duplicated(), index=order.index).reindex(sub.index)
        dup.loc[sub.index] = multi & ~first
    df.loc[dup, "처리"] = df.loc[dup, "처리"] + " + 중복제거"

    log = df.loc[df["처리"] != "그대로", ["원래코드", "sgg_nm", "emd_cd", "읍면동명_사용", "sub_nm", "sub_id",
                                          "신코드", "처리"]].assign(블록=p)
    kept = df[ok & ~dup].copy()
    nm = std.set_index("code")
    kept["sido_cd"] = kept["신코드"].str[:2]
    kept["sgg_cd"] = kept["신코드"].str[2:]
    kept["sido_nm"] = kept["신코드"].map(nm["시도명"])
    kept["sgg_nm"] = kept["신코드"].map(nm["시군구"])
    vc = df["처리"].value_counts().to_dict()
    print(f"  {p}: {len(df)}행 → {len(kept)}행  {vc}")
    return kept.drop(columns=["원래코드", "신코드", "처리", "읍면동명_사용", "sub_id", "sub_nm"]), log


def remap_345(raws, res, std):
    mpath = os.path.join(kc.SAVE_DIR, kc.F_MASTER)
    if raws["c345"] is None or not os.path.exists(mpath):
        print("  c345: 원본 또는 지역마스터 없음 — 건너뜀")
        return None, set(), pd.DataFrame()
    kmaster = read_csv(mpath)
    cmap, unmatched = kc.map_supply_area(raws["c345"], kmaster)
    cmap = cmap[cmap["sgg_cd"] != ""]
    direct, copied, rows, bad = set(), set(), [], []
    for sub, c5 in zip(cmap["sub_idx"], cmap["sido_cd"] + cmap["sgg_cd"]):
        tgt, is_copy = res.resolve_all(c5)
        if not tgt:
            bad.append({"원래코드": c5, "sub_nm": raws["c345"].loc[sub, "변전소"], "처리": "미배정(기준표에 없는 코드)"})
        for t in tgt:
            rows.append((sub, t))
            (copied if is_copy else direct).add((sub, t))
    mp = pd.DataFrame(sorted(set(rows)), columns=["sub_idx", "code"])
    mp["sido_cd"], mp["sgg_cd"] = mp["code"].str[:2], mp["code"].str[2:]
    shared = {t for s, t in copied - direct}
    log = pd.DataFrame([{"원래코드": "", "sub_nm": raws["c345"].loc[s, "변전소"], "신코드": t,
                         "처리": "345kV 상위지역 복제"} for s, t in sorted(copied - direct)] + bad).assign(블록="c345")
    print(f"  c345: 매핑 {len(mp)}건 (상위지역 복제 {len(copied - direct)}건, 미배정 {len(bad)}건), "
          f"공급지역 텍스트 미매칭 토큰 {len(unmatched)}건")
    return mp.drop(columns="code").merge(kc.norm_c345(raws["c345"]), on="sub_idx"), shared, log


def todo_list(logs):
    """매핑에 없는 읍면동 → 개편매핑_법정동.csv 형식으로"""
    t = logs[logs["처리"].str.startswith("미배정(매핑에 없는") | logs["처리"].str.startswith("미배정(읍면동코드 모호")]
    if t.empty:
        return t
    t = t.assign(읍면동명=t["읍면동명_사용"].str.split(" / ")).explode("읍면동명")
    return t.groupby(["원래코드", "sgg_nm", "읍면동명"], as_index=False).agg(블록=("블록", lambda x: ",".join(sorted(set(x))))) \
        .rename(columns={"원래코드": "개편전코드", "sgg_nm": "원래시군구명"}).assign(신코드="", 신시군구명="", 근거="")


# ── 메인 ─────────────────────────────────────────────────────
def main(force=False):
    kc.banner("2단계: 256 시군구 재배정 · 재집계")
    std = load_std()
    res = Resolver(std, load_map(std))
    raws, norm = load_blocks()
    lookup = emd_name_lookup(norm)

    remapped, logs = {}, []
    for p, (df, metrics) in norm.items():
        kept, log = remap_block(p, df, res, std, lookup)
        remapped[p] = (kept, metrics)
        logs.append(log)
    logs = pd.concat(logs, ignore_index=True)

    todo = todo_list(logs)
    if len(todo):
        kc.save_csv(todo, F_TODO)
        print(f"!! 개편매핑에 없는 읍면동 {len(todo)}개 → {F_TODO}의 신코드·신시군구명을 채워 {F_MAP}에 추가 후 재실행")
        print(todo[["개편전코드", "원래시군구명", "읍면동명", "블록"]].to_string(index=False))
        if not force:
            sys.exit("   중단 (--force로 강행 가능: 이 행들은 결과에서 빠짐)")

    c345, shared, log345 = remap_345(raws, res, std)
    if len(log345):
        logs = pd.concat([logs, log345], ignore_index=True)

    blocks = [(p, df, m) for p, (df, m) in remapped.items()]
    if c345 is not None:
        blocks.append(("c345", c345, list(kc.C345_MAP)))
    frames = [df for df, _ in remapped.values()]
    coverage = {p: set(df["sido_cd"]) for p, (df, _) in remapped.items()}
    master = pd.DataFrame({"sido_cd": std["code"].str[:2], "sido_nm": std["시도명"],
                           "sgg_cd": std["code"].str[2:], "sgg_nm": std["시군구"]})
    wide = kc.build_level("sgg", blocks, master, frames, coverage)

    # 기준표 순서로 정렬 + feature_v3.py가 쓰는 플래그
    wide = wide.set_index("지역코드").reindex(std["code"]).reset_index().rename(columns={"code": "지역코드"})
    assert len(wide) == len(std) and wide["시도명"].ne("").all(), "기준표에 없는 코드가 섞였거나 행이 빠짐"
    n_site = [c for c in wide.columns if c.endswith("_변전소수") and not c.startswith("차단기_공급지역기준")]
    wide["345kV_상위지역공유"] = wide["지역코드"].isin(shared)
    wide["변전소응답없음"] = wide[n_site].sum(axis=1) == 0
    kc.save_csv(wide, F_OUT)
    kc.save_csv(logs.rename(columns={"sgg_nm": "원래시군구명", "emd_cd": "읍면동코드", "읍면동명_사용": "읍면동명",
                                     "sub_nm": "변전소", "sub_id": "변전소ID"}), F_LOG)

    print(f"\n[요약] {len(wide)}행 x {wide.shape[1]}열")
    print("  처리 건수:", logs["처리"].value_counts().to_dict())
    cov = [c for c in wide.columns if c.endswith("_데이터있음")]
    print("  시도별 데이터있음(블록 수):",
          wide.groupby("시도명")[cov].max().sum(axis=1).astype(int).to_dict())
    print(f"  변전소응답없음 {int(wide['변전소응답없음'].sum())}곳:",
          (wide.loc[wide["변전소응답없음"], "시도명"] + " " + wide.loc[wide["변전소응답없음"], "시군구명"]).tolist())
    print(f"  345kV 상위지역공유: {sorted(shared)}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)