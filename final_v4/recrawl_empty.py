"""
전력공급 여유용량(22.9kV/154kV) '빈 응답' 시군구만 다시 조회해 원본 CSV에 보충
================================================================================
배경 (2026-10-06): crawl_per_gu는 '요청 실패'만 재시도하고 '빈 배열 응답'은 정상으로 받아들임.
  10-04 대비 22.9kV가 0이 된 지역(파주 12→0, 김포 12→0, 세종 8→0 등 15곳 이상)과
  종로 154kV(8→0)는 일시적 빈 응답일 가능성이 높아, 해당 시군구만 최대 3라운드 재조회한다.
  재조회 후에도 비어 있으면 실제로 공개 데이터가 없는 것으로 보고 그대로 둔다(사이트에서 직접 확인 권장).

실행 (final_v4 폴더, kepco_crawler.py와 같은 폴더)
  python recrawl_empty.py
  → 원본 CSV를 *.bak_{날짜시각} 으로 백업한 뒤 보충본으로 덮어씀
  → 이어서 python step2_시군구.py → python step3_분석대상.py 다시 실행
"""
import os
import shutil
import time
from datetime import datetime
import pandas as pd
import kepco_crawler as kc

VOLTS = {"23": kc.F_SUP229, "154": kc.F_SUP154}
ROUNDS, SLEEP, WAITS = 3, 0.5, (5, 10)


def dedup_like_crawler(df):
    """kepco_crawler.energy_rows_to_df와 같은 규칙: 완전 중복 제거 + (시도,시군구,관리번호) 1행"""
    df = df.drop_duplicates().reset_index(drop=True)
    mgmt = df["변전소관리번호"].astype(str).str.strip()
    has = mgmt.ne("") & mgmt.ne("nan")
    key = df["시도코드"].astype(str) + "|" + df["시군구코드"].astype(str) + "|" + mgmt
    return df.loc[~(has & key.duplicated())].reset_index(drop=True)


def recrawl(volt, fname, tasks, headers):
    label = "22.9kV" if volt == "23" else "154kV"
    raw = kc.read_raw(fname)
    if raw is None:
        print(f"!! {fname} 없음 — 건너뜀")
        return
    have = set(raw["시도코드"].astype(str).str.zfill(2) + raw["시군구코드"].astype(str).str.zfill(3))
    pending = [t for t in tasks if t.sido_cd + t.sgg_cd not in have]
    kc.banner(f"{label}: 빈 응답 시군구 {len(pending)}개 재조회")
    key = f"dma_subSt{volt}"
    url = f"{kc.BASE}/ew/api/energy/subSt{volt}"
    got, recovered = [], []
    for rnd in range(ROUNDS):
        still = []
        for t in pending:
            payload = {key: {"sidoCode": t.sido_cd, "siggCode": t.sgg_req_cd, "emdCode": "", "year": kc.YEAR}}
            rows = kc.post_rows(url, payload, headers, f"{key}list")
            time.sleep(SLEEP)
            if rows:
                for r in rows:
                    r["_t"] = t
                got.extend(rows)
                recovered.append(f"{t.sido_nm} {t.sgg_nm}({len(rows)})")
            else:
                still.append(t)
        print(f"  라운드 {rnd + 1}: 복구 {len(pending) - len(still)}개, 남음 {len(still)}개")
        pending = still
        if not pending or rnd == ROUNDS - 1:
            break
        time.sleep(WAITS[min(rnd, len(WAITS) - 1)])

    print(f"  복구된 시군구: {recovered or '없음'}")
    print(f"  끝까지 빈 시군구 {len(pending)}개: {[f'{t.sido_nm} {t.sgg_nm}' for t in pending]}")
    if not got:
        print("  보충할 행 없음 — 원본 유지")
        return
    new = kc.energy_rows_to_df(got)
    # 보충 행은 원본에 없던 시군구 것뿐이라 원본 행과 겹치지 않음. 시군구 안 중복만 크롤러 규칙으로 정리
    merged = dedup_like_crawler(pd.concat([raw, new], ignore_index=True))
    path = os.path.join(kc.SAVE_DIR, fname)
    bak = f"{path}.bak_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(path, bak)
    kc.save_csv(merged, fname)
    print(f"  {len(raw)}행 → {len(merged)}행 (+{len(merged) - len(raw)}), 백업: {os.path.basename(bak)}")


def main():
    em_path = os.path.join(kc.SAVE_DIR, kc.F_ENERGY_MASTER)
    em = pd.read_csv(em_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    tasks = list(em[em["sgg_cd"] != ""].itertuples(index=False))
    headers = kc.headers_for("EWM104D04")
    for volt, fname in VOLTS.items():
        recrawl(volt, fname, tasks, headers)
    print("\n다음: python step2_시군구.py → python step3_분석대상.py")


if __name__ == "__main__":
    main()