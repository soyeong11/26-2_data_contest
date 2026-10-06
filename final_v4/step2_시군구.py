"""
2단계: KEPCO 시군구 → 팀 256 시군구 기준으로 재배정 후 wide 재집계
(kepco_crawler.py와 같은 폴더에 두고 실행. 크롤러의 정규화·집계·한글컬럼 함수를 그대로 재사용하므로
 출력 컬럼명은 지역별_시군구_wide.csv와 동일 → 이후 전력피쳐 코드에 그대로 연결됨)

실행
  python step2_시군구256.py            매핑표가 비어 있는 시군구가 있으면 템플릿만 저장하고 중단
  python step2_시군구256.py --force    미배정 행을 제외한 채 강행 (권장 X)

왜 wide가 아니라 '원본(변전소 단위)'에서 다시 집계하나
  - 신설구는 읍면동 단위로 갈라야 하는데, 읍면동 wide는 크롤러의 (시도,시군구,관리번호) 중복제거 때문에
    일부 읍면동 행이 빠져 있음 → 읍면동 wide를 합치면 합계/변전소수가 틀어짐
  - 원본에서 변전소마다 새 시군구를 붙인 뒤 다시 집계하면 합계·최대·변전소수가 모두 정확함

입력 (데이터셋/ 폴더)
  [크롤러 산출물] 원본 CSV 5종 + 지역마스터_시군구.csv
  [직접 준비]
  기준_시군구256.csv      (필수) 시도코드, 시도명, 시군구코드, 시군구명  ← 팀 256 기준표
  매핑_신설구_읍면동.csv   (필요시) 원시도명, 원시군구명, 읍면동명, 신시군구명
                          KEPCO의 한 시군구가 기준표에서 여러 구로 갈린 경우 (예: 화성시 → 신설 4개 구,
                          인천 중구/서구 → 신설구). 여기 등록된 원시군구는 '이름이 그대로 있어도' 반드시
                          읍면동 기준으로 배정됨 (예: 인천 중구가 기준표에도 있지만 일부 동이 다른 구로 감)
  매핑_시군구_수동.csv     (선택) 원시도명, 원시군구명, 신시도명, 신시군구명
                          이름이 달라 자동매칭이 안 되는 시군구를 통째로 매핑 (예: 경상북도 군위군 → 대구광역시 군위군)
매칭은 '이름' 기준(시도는 크롤러의 별칭표로 정규화, 시군구·읍면동은 공백 제거).
코드 체계가 네임스페이스마다 달라서 코드보다 이름이 안전함.

출력 (데이터셋/ 폴더)
  지역별_시군구256_wide.csv          1행 = 기준표 1개 시군구 (행 수 = 기준표 행 수)
  2단계_읍면동매핑_템플릿.csv         기준표와 이름이 안 맞는 KEPCO 시군구의 읍면동 목록 (신시군구명 빈칸 → 채워서
                                     매핑_신설구_읍면동.csv로 저장)
  2단계_미배정.csv                    배정 못 한 변전소 행 (매핑표에 없는 읍면동, 읍면동명 없음 등)
  2단계_345kV_미배정.csv              345kV 공급가능지역 중 기준표로 못 옮긴 항목

한계
  - 변전소 1개 = 시군구 1개(크롤러 중복제거 때 남은 읍면동 기준). 경계에 걸친 공유 변전소는 한쪽에만 들어감.
  - 차단기(cbr) 원본에는 읍면동명이 없어서, 같은 cpct 네임스페이스인 재생e 원본의 (시도,시군구,읍면동코드)→읍면동명
    사전으로 채움. 사전에 없는 읍면동코드는 '2단계_미배정.csv'로 나옴.
  - 345kV는 공급가능지역 텍스트가 시군구 단위라 읍면동을 알 수 없음 → 쪼개진 시군구면 신설구 전체에 중복 반영
    (크롤러의 '성남시 → 3개 구 전체' 규칙과 같은 방식).
"""
import os
import sys
import pandas as pd
import kepco_crawler as kc

F_STD = "기준_시군구256.csv"
F_MAP_EMD = "매핑_신설구_읍면동.csv"
F_MAP_SGG = "매핑_시군구_수동.csv"
F_OUT = "지역별_시군구256_wide.csv"
F_TEMPLATE = "2단계_읍면동매핑_템플릿.csv"
F_UNRES = "2단계_미배정.csv"
F_UNRES_345 = "2단계_345kV_미배정.csv"

_SIDO_KEY = {a: off for off, al in kc._SIDO_ALIAS_GROUPS.items() for a in al}


def sido_key(x):
    s = "" if pd.isna(x) else str(x).strip()
    return _SIDO_KEY.get(s, s)


def nm_key(x):
    return "" if pd.isna(x) else str(x).replace(" ", "").strip()


def read_input(fname, cols, required=False):
    p = os.path.join(kc.SAVE_DIR, fname)
    if not os.path.exists(p):
        if required:
            sys.exit(f"!! 필수 입력 없음: {p}")
        return None
    df = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    miss = [c for c in cols if c not in df.columns]
    if miss:
        sys.exit(f"!! {fname} 에 컬럼 없음: {miss} (필요: {cols})")
    return df


def load_std():
    raw = read_input(F_STD, ["시도코드", "시도명", "시군구코드", "시군구명"], required=True)
    std = pd.DataFrame({
        "sido_cd": raw["시도코드"].map(lambda x: kc.norm_cd(x, 2)),
        "sido_nm": raw["시도명"].str.strip(),
        "sgg_cd": raw["시군구코드"].map(kc.sgg3),      # 5자리로 와도 뒤 3자리
        "sgg_nm": raw["시군구명"].str.strip(),
    })
    std["k"] = list(zip(std["sido_nm"].map(sido_key), std["sgg_nm"].map(nm_key)))
    if std["k"].duplicated().any():
        sys.exit(f"!! 기준표에 같은 (시도,시군구) 이름이 2번 이상: {std.loc[std['k'].duplicated(keep=False), 'sgg_nm'].tolist()}")
    if std.duplicated(["sido_cd", "sgg_cd"]).any():
        sys.exit("!! 기준표에 같은 (시도코드,시군구코드)가 2번 이상 — 시군구코드가 시도 안에서 유일한지 확인")
    print(f"  기준표: {len(std)}행")
    return std


class Resolver:
    def __init__(self, std, map_emd, map_sgg):
        self.by_key = {k: (r.sido_cd, r.sido_nm, r.sgg_cd, r.sgg_nm)
                       for k, r in zip(std["k"], std.itertuples(index=False))}
        self.override, self.emd, self.children = {}, {}, {}
        if map_sgg is not None:
            for a, b, c, d in map_sgg[["원시도명", "원시군구명", "신시도명", "신시군구명"]].itertuples(index=False):
                self.override[(sido_key(a), nm_key(b))] = (sido_key(c), nm_key(d))
        if map_emd is not None:
            for a, b, e, n in map_emd[["원시도명", "원시군구명", "읍면동명", "신시군구명"]].itertuples(index=False):
                if not nm_key(n):
                    continue
                pk = (sido_key(a), nm_key(b))
                ck = (pk[0], nm_key(n))
                if ck not in self.by_key:
                    sys.exit(f"!! 매핑_신설구_읍면동: 신시군구명 '{n}'({a})이 기준표에 없음")
                self.emd[pk + (nm_key(e),)] = ck
                self.children.setdefault(pk, set()).add(ck)
        for src, dst in self.override.items():
            if dst not in self.by_key:
                sys.exit(f"!! 매핑_시군구_수동: {dst}가 기준표에 없음")

    def resolve(self, sido_nm, sgg_nm, emd_nm):
        """반환: (기준표 튜플 또는 None, 방법)"""
        pk = (sido_key(sido_nm), nm_key(sgg_nm))
        if pk in self.children:                      # 쪼개진 시군구 → 읍면동 기준 (이름이 기준표에 있어도)
            ck = self.emd.get(pk + (nm_key(emd_nm),))
            return (self.by_key[ck], "읍면동") if ck else (None, "읍면동매핑없음")
        k = self.override.get(pk, pk)
        hit = self.by_key.get(k)
        return (hit, "수동" if k != pk else "이름") if hit else (None, "시군구불일치")

    def resolve_sgg_all(self, sido_nm, sgg_nm):
        """345kV용: 쪼개진 시군구면 신설구 전체"""
        pk = (sido_key(sido_nm), nm_key(sgg_nm))
        if pk in self.children:
            return [self.by_key[c] for c in sorted(self.children[pk])]
        hit = self.by_key.get(self.override.get(pk, pk))
        return [hit] if hit else []


def remap_frame(df, res, label, unres):
    hits, how = zip(*[res.resolve(a, b, c) for a, b, c in
                      df[["sido_nm", "sgg_nm", "emd_nm"]].itertuples(index=False)]) if len(df) else ((), ())
    df = df.copy()
    df["_how"] = list(how)
    ok = df["_how"].isin(["이름", "수동", "읍면동"])
    bad = df.loc[~ok, ["sido_nm", "sgg_nm", "emd_cd", "emd_nm", "_how"]].assign(블록=label)
    unres.append(bad)
    df = df.loc[ok].copy()
    got = [h for h, o in zip(hits, ok) if o]
    for i, c in enumerate(["sido_cd", "sido_nm", "sgg_cd", "sgg_nm"]):
        df[c] = [g[i] for g in got]
    print(f"  {label}: {len(df)}행 배정 ({df['_how'].value_counts().to_dict()}), 미배정 {len(bad)}행")
    return df.drop(columns="_how").reset_index(drop=True)


def make_template(frames_raw, res):
    """기준표에 이름이 없고 매핑도 없는 KEPCO 시군구 → 그 시군구의 읍면동 목록"""
    allf = pd.concat([f[["sido_nm", "sgg_nm", "emd_nm"]] for f in frames_raw], ignore_index=True)
    rows = []
    for (s, g), grp in allf.groupby(["sido_nm", "sgg_nm"]):
        pk = (sido_key(s), nm_key(g))
        if pk in res.children or res.override.get(pk, pk) in res.by_key:
            continue
        emds = sorted({e for e in grp["emd_nm"] if nm_key(e)}) or [""]
        rows += [{"원시도명": s, "원시군구명": g, "읍면동명": e, "신시군구명": ""} for e in emds]
    return pd.DataFrame(rows, columns=["원시도명", "원시군구명", "읍면동명", "신시군구명"])


def main(force=False):
    kc.banner("2단계: 256 시군구 재배정")
    std = load_std()
    res = Resolver(std,
                   read_input(F_MAP_EMD, ["원시도명", "원시군구명", "읍면동명", "신시군구명"]),
                   read_input(F_MAP_SGG, ["원시도명", "원시군구명", "신시도명", "신시군구명"]))
    print(f"  신설구 매핑: 원시군구 {len(res.children)}개 / 읍면동 {len(res.emd)}개, 수동 시군구 매핑 {len(res.override)}개")

    raws = {"sup229": kc.read_raw(kc.F_SUP229), "sup154": kc.read_raw(kc.F_SUP154),
            "renw": kc.read_raw(kc.F_RENW), "cbr": kc.read_raw(kc.F_CBR), "c345": kc.read_raw(kc.F_C345)}
    norm = {}
    if raws["sup229"] is not None: norm["sup229"] = (kc.norm_energy(raws["sup229"]), kc.E_METRICS)
    if raws["sup154"] is not None: norm["sup154"] = (kc.norm_energy(raws["sup154"]), kc.E_METRICS)
    if raws["renw"] is not None: norm["renw"] = (kc.norm_energy(raws["renw"], renewable=True), kc.R_METRICS)
    if raws["cbr"] is not None: norm["cbr"] = (kc.norm_cbr(raws["cbr"]), list(kc.CBR_MAP))
    if not norm:
        sys.exit("!! 원본 CSV가 없습니다. 크롤링 먼저.")

    # 차단기 원본엔 읍면동명이 없음 → 재생e(같은 cpct 네임스페이스)의 코드→이름 사전으로 채움
    if "cbr" in norm:
        cbr = norm["cbr"][0]
        cbr["emd_nm"] = ""
        if "renw" in norm:
            lk = norm["renw"][0][["sido_cd", "sgg_cd", "emd_cd", "emd_nm"]]
            lk = lk[lk["emd_nm"].map(nm_key) != ""].drop_duplicates(["sido_cd", "sgg_cd", "emd_cd"])
            cbr = cbr.drop(columns="emd_nm").merge(lk, on=["sido_cd", "sgg_cd", "emd_cd"], how="left")
            cbr["emd_nm"] = cbr["emd_nm"].fillna("")
        norm["cbr"] = (cbr, norm["cbr"][1])

    tmpl = make_template([df for df, _ in norm.values()], res)
    if len(tmpl):
        kc.save_csv(tmpl, F_TEMPLATE)
        print(f"!! 기준표와 이름이 안 맞는 KEPCO 시군구 {tmpl.groupby(['원시도명', '원시군구명']).ngroups}개: "
              f"{tmpl[['원시도명', '원시군구명']].drop_duplicates().apply(' '.join, axis=1).tolist()}")
        print(f"   → {F_TEMPLATE}의 신시군구명을 채워 {F_MAP_EMD}에 추가하거나, 통째 매핑이면 {F_MAP_SGG}에 추가")
        if not force:
            sys.exit("   중단 (--force로 강행 가능, 이 시군구들은 결과에서 빠짐)")

    unres = []
    remapped = {p: (remap_frame(df, res, p, unres), m) for p, (df, m) in norm.items()}
    frames = [df for df, _ in remapped.values()]
    coverage = {p: set(df["sido_cd"]) for p, (df, _) in remapped.items()}
    blocks = [(p, df, m) for p, (df, m) in remapped.items()]

    # 345kV: KEPCO cpct 마스터 기준으로 매핑한 뒤 기준표로 옮김
    mpath = os.path.join(kc.SAVE_DIR, kc.F_MASTER)
    if raws["c345"] is not None and os.path.exists(mpath):
        kmaster = pd.read_csv(mpath, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        cmap, _ = kc.map_supply_area(raws["c345"], kmaster)
        names = kmaster[["sido_cd", "sido_nm", "sgg_cd", "sgg_nm"]].drop_duplicates(["sido_cd", "sgg_cd"])
        m = cmap[cmap["sgg_cd"] != ""].merge(names, on=["sido_cd", "sgg_cd"], how="left")
        rows, bad = [], []
        for sub, s, g in m[["sub_idx", "sido_nm", "sgg_nm"]].itertuples(index=False):
            tg = res.resolve_sgg_all(s, g)
            if not tg:
                bad.append({"변전소": raws["c345"].loc[sub, "변전소"], "시도": s, "시군구": g})
            rows += [(sub, t[0], t[2]) for t in tg]
        mp = pd.DataFrame(rows, columns=["sub_idx", "sido_cd", "sgg_cd"]).drop_duplicates()
        blocks.append(("c345", mp.merge(kc.norm_c345(raws["c345"]), on="sub_idx"), list(kc.C345_MAP)))
        kc.save_csv(pd.DataFrame(bad, columns=["변전소", "시도", "시군구"]), F_UNRES_345)
        print(f"  c345: 매핑 {len(mp)}건, 기준표로 못 옮김 {len(bad)}건")
    else:
        print("  c345: 원본 또는 지역마스터 없음 — 건너뜀")

    master = std[["sido_cd", "sido_nm", "sgg_cd", "sgg_nm"]]
    wide = kc.build_level("sgg", blocks, master, frames, coverage)
    assert len(wide) == len(std), f"행 수 불일치: wide {len(wide)} vs 기준표 {len(std)}"
    kc.save_csv(wide, F_OUT)

    ub = pd.concat(unres, ignore_index=True)
    kc.save_csv(ub.rename(columns={"sido_nm": "시도", "sgg_nm": "시군구", "emd_cd": "읍면동코드",
                                   "emd_nm": "읍면동", "_how": "사유"}), F_UNRES)

    sub_cols = [c for c in wide.columns if c.endswith("_변전소수")]
    empty = wide[wide[sub_cols].sum(axis=1) == 0]
    print(f"\n[요약] {len(wide)}행 x {wide.shape[1]}열, 미배정 변전소 행 {len(ub)}개")
    if len(empty):
        print(f"  모든 블록에서 변전소 0개인 시군구 {len(empty)}개 (실제로 없는지 vs 매핑 누락인지 확인): "
              f"{(empty['시도명'] + ' ' + empty['시군구명']).tolist()[:20]}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)