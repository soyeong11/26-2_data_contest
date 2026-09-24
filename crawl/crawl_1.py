"""
KEPCO (한전 온) 종합 데이터 크롤러
출처: https://online.kepco.co.kr/EWM088D00

수집 대상 메뉴:
1. 재생e 연계 여유용량 (EWM094D00)
2. 전력공급 여유용량 (EWM104D04)
3. 22.9kV / 154kV 차단기 여유 Bay (EWM100D00)
4. 345kV 변전소 차단기 여유 Bay (EWM100D01)

출력:
  - 데이터셋/재생e_연계여유용량.csv
  - 데이터셋/전력공급_여유용량.csv
  - 데이터셋/차단기_여유Bay_154kV.csv
  - 데이터셋/차단기_여유Bay_345kV.csv
  - 데이터셋/KEPCO_전력망_종합통합.csv
"""

import os
import time
from datetime import datetime
import pandas as pd
import requests

BASE = "https://online.kepco.co.kr"
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "데이터셋")
os.makedirs(SAVE_DIR, exist_ok=True)

# 공통 헤더 생성 함수
def get_headers(menu_id):
    return {
        "Content-Type": 'application/json; charset="UTF-8"',
        "Referer": f"{BASE}/{menu_id}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def api_post(url, payload, headers, retry=3):
    """안정적인 API 요청 처리 (재시도 및 백오프 적용)"""
    for attempt in range(retry):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < retry - 1:
                time.sleep(2**attempt)
    return None


# ── 1. 재생e 연계 여유용량 (EWM094D00) ─────────────────────────────
def crawl_renw_supply():
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 1. 재생e 연계 여유용량 크롤링 시작 (EWM094D00)")
    print("=" * 60)

    headers = get_headers("EWM094D00")
    final_path = os.path.join(SAVE_DIR, "재생e_연계여유용량.csv")
    interim_path = os.path.join(SAVE_DIR, "_interim_renw.csv")

    d = api_post(f"{BASE}/ew/api/energy/selectDo", {}, headers)
    sido_list = d.get("dma_Dolist", []) if d else []

    all_rows, done_gu = load_interim(interim_path)

    for si, sido in enumerate(sido_list, 1):
        sido_code, sido_nm = sido["NSDIP_ALL_ADDR_CD"], sido["ADDR_NM"]
        d2 = api_post(
            f"{BASE}/ew/api/energy/selectGu",
            {"dma_viewMap": {"Do": sido_code}},
            headers,
        )
        gu_list = d2.get("dma_Gulist", []) if d2 else []
        time.sleep(0.2)

        print(f"[{si:02d}/{len(sido_list)}] {sido_nm} ({len(gu_list)}개 시군구)")

        for gi, gu in enumerate(gu_list, 1):
            sigg_code_5 = gu["NSDIP_ALL_ADDR_CD"]
            sigg_nm = gu["ADDR_NM"]
            sigg_code_3 = (
                sigg_code_5[2:] if len(sigg_code_5) >= 5 else sigg_code_5
            )

            if (sido_code, sigg_code_5) in done_gu:
                continue

            # 재생e 연계 여유용량 API
            d3 = api_post(
                f"{BASE}/ew/api/energy/subStRenw",
                {
                    "dma_subStRenw": {
                        "sidoCode": sido_code,
                        "siggCode": sigg_code_3,
                        "emdCode": "",
                    }
                },
                headers,
            )
            rows = d3.get("dma_subStRenwlist", []) if d3 else []
            time.sleep(0.25)

            for row in rows:
                all_rows.append(
                    {
                        "시도": row.get("SIDO_NM", sido_nm),
                        "시군구": row.get("SGG_NM", sigg_nm),
                        "변전소": row.get("PSPWP_NM", row.get("PSPWPNM", "")),
                        "재생e_여유용량_MW": row.get("RENW_CAPA", ""),
                        "_sido_code": sido_code,
                        "_sigg_code": sigg_code_5,
                    }
                )

            done_gu.add((sido_code, sigg_code_5))
            if len(done_gu) % 15 == 0:
                pd.DataFrame(all_rows).to_csv(
                    interim_path, index=False, encoding="utf-8-sig"
                )

    return save_and_clean(all_rows, interim_path, final_path, ["재생e_여유용량_MW"])


# ── 2. 전력공급 여유용량 (EWM104D04) ───────────────────────────────
def crawl_power_supply():
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 2. 전력공급 여유용량 크롤링 시작 (EWM104D04)")
    print("=" * 60)

    headers = get_headers("EWM104D04")
    final_path = os.path.join(SAVE_DIR, "전력공급_여유용량.csv")
    interim_path = os.path.join(SAVE_DIR, "_interim_power.csv")

    d = api_post(f"{BASE}/ew/api/energy/selectDo", {}, headers)
    sido_list = d.get("dma_Dolist", []) if d else []

    all_rows, done_gu = load_interim(interim_path)

    for si, sido in enumerate(sido_list, 1):
        sido_code, sido_nm = sido["NSDIP_ALL_ADDR_CD"], sido["ADDR_NM"]
        d2 = api_post(
            f"{BASE}/ew/api/energy/selectGu",
            {"dma_viewMap": {"Do": sido_code}},
            headers,
        )
        gu_list = d2.get("dma_Gulist", []) if d2 else []
        time.sleep(0.2)

        print(f"[{si:02d}/{len(sido_list)}] {sido_nm} ({len(gu_list)}개 시군구)")

        for gi, gu in enumerate(gu_list, 1):
            sigg_code_5 = gu["NSDIP_ALL_ADDR_CD"]
            sigg_nm = gu["ADDR_NM"]
            sigg_code_3 = (
                sigg_code_5[2:] if len(sigg_code_5) >= 5 else sigg_code_5
            )

            if (sido_code, sigg_code_5) in done_gu:
                continue

            d3 = api_post(
                f"{BASE}/ew/api/energy/subSt154",
                {
                    "dma_subSt154": {
                        "sidoCode": sido_code,
                        "siggCode": sigg_code_3,
                        "emdCode": "",
                        "year": "2026",
                    }
                },
                headers,
            )
            rows = d3.get("dma_subSt154list", []) if d3 else []
            time.sleep(0.25)

            for row in rows:
                all_rows.append(
                    {
                        "시도": row.get("SIDO_NM", sido_nm),
                        "시군구": row.get("SGG_NM", sigg_nm),
                        "읍면동": row.get("EMD_NM", ""),
                        "변전소": row.get("PSPWP_NM", row.get("PSPWPNM", "")),
                        "전력공급여유_2026": row.get("THIS_YY", ""),
                        "전력공급여유_2027": row.get("ONE_YY", ""),
                        "전력공급여유_2028": row.get("TWO_YY", ""),
                        "전력공급여유_2029": row.get("THR_YY", ""),
                        "전력공급여유_2030": row.get("FOR_YY", ""),
                        "전력공급여유_2031": row.get("FIV_YY", ""),
                        "전력공급여유_2032": row.get("SIX_YY", ""),
                        "_sido_code": sido_code,
                        "_sigg_code": sigg_code_5,
                    }
                )

            done_gu.add((sido_code, sigg_code_5))
            if len(done_gu) % 15 == 0:
                pd.DataFrame(all_rows).to_csv(
                    interim_path, index=False, encoding="utf-8-sig"
                )

    year_cols = [f"전력공급여유_{y}" for y in range(2026, 2033)]
    return save_and_clean(all_rows, interim_path, final_path, year_cols)


# ── 3. 22.9kV / 154kV 차단기 여유 Bay (EWM100D00) ────────────────────
def crawl_cbr_154():
    print(f"\n{'='*60}")
    print(
        f"[{datetime.now():%H:%M:%S}] 3. 22.9kV/154kV 차단기 여유 Bay 크롤링 (EWM100D00)"
    )
    print("=" * 60)

    headers = get_headers("EWM100D00")
    final_path = os.path.join(SAVE_DIR, "차단기_여유Bay_154kV.csv")
    interim_path = os.path.join(SAVE_DIR, "_interim_cbr154.csv")

    d = api_post(f"{BASE}/ew/cpct/selectChangeDoMapJson", {}, headers)
    sido_list = d.get("dlt_sido", []) if d else []

    all_rows, done_gu = load_interim(interim_path)

    for si, sido in enumerate(sido_list, 1):
        sido_code, sido_nm = sido["NSDIP_ALL_ADDR_CD"], sido["ADDR_NM"]
        d2 = api_post(
            f"{BASE}/ew/cpct/selectChangeGuMapJson",
            {
                "dma_reqParam": {
                    "sido_code": sido_code,
                    "sigg_code": "",
                    "emd_code": "",
                }
            },
            headers,
        )
        gu_list = d2.get("dlt_gu", []) if d2 else []
        time.sleep(0.2)

        print(f"[{si:02d}/{len(sido_list)}] {sido_nm} ({len(gu_list)}개 시군구)")

        for gi, gu in enumerate(gu_list, 1):
            sigg_code, sigg_nm = gu["NSDIP_ALL_ADDR_CD"], gu["ADDR_NM"]

            if (sido_code, sigg_code) in done_gu:
                continue

            d3 = api_post(
                f"{BASE}/ew/cpct/retrieveCbrOvplsInfo",
                {
                    "dma_reqParam": {
                        "sido_code": sido_code,
                        "sigg_code": sigg_code,
                        "emd_code": "",
                    }
                },
                headers,
            )
            rows = d3.get("dlt_resultList", []) if d3 else []
            time.sleep(0.25)

            for row in rows:
                all_rows.append(
                    {
                        "시도": sido_nm,
                        "시군구": sigg_nm,
                        "변전소": row.get("S_NM", row.get("SNM", "")),
                        "변전소코드": row.get("S_CD", ""),
                        "154kV_차단기_전체": row.get("B005_TOTAL_BAY", 0),
                        "154kV_차단기_사용중": row.get("B005_USE_BAY_TO", 0),
                        "154kV_차단기_사용예정": row.get("B005_SUBS_BAY", 0),
                        "154kV_차단기_여유": row.get("B005_FUTU_BAY", 0),
                        "_sido_code": sido_code,
                        "_sigg_code": sigg_code,
                    }
                )

            done_gu.add((sido_code, sigg_code))
            if len(done_gu) % 15 == 0:
                pd.DataFrame(all_rows).to_csv(
                    interim_path, index=False, encoding="utf-8-sig"
                )

    bay_cols = [
        "154kV_차단기_전체",
        "154kV_차단기_사용중",
        "154kV_차단기_사용예정",
        "154kV_차단기_여유",
    ]
    return save_and_clean(all_rows, interim_path, final_path, bay_cols)


# ── 4. 345kV 변전소 차단기 여유 Bay (EWM100D01) ────────────────────
def crawl_cbr_345():
    print(f"\n{'='*60}")
    print(
        f"[{datetime.now():%H:%M:%S}] 4. 345kV 차단기 여유 Bay 크롤링 (EWM100D01)"
    )
    print("=" * 60)

    headers = get_headers("EWM100D01")
    final_path = os.path.join(SAVE_DIR, "차단기_여유Bay_345kV.csv")
    interim_path = os.path.join(SAVE_DIR, "_interim_cbr345.csv")

    d = api_post(f"{BASE}/ew/cpct/selectChangeDoMapJson", {}, headers)
    sido_list = d.get("dlt_sido", []) if d else []

    all_rows, done_gu = load_interim(interim_path)

    for si, sido in enumerate(sido_list, 1):
        sido_code, sido_nm = sido["NSDIP_ALL_ADDR_CD"], sido["ADDR_NM"]
        d2 = api_post(
            f"{BASE}/ew/cpct/selectChangeGuMapJson",
            {
                "dma_reqParam": {
                    "sido_code": sido_code,
                    "sigg_code": "",
                    "emd_code": "",
                }
            },
            headers,
        )
        gu_list = d2.get("dlt_gu", []) if d2 else []
        time.sleep(0.2)

        print(f"[{si:02d}/{len(sido_list)}] {sido_nm} ({len(gu_list)}개 시군구)")

        for gi, gu in enumerate(gu_list, 1):
            sigg_code, sigg_nm = gu["NSDIP_ALL_ADDR_CD"], gu["ADDR_NM"]

            if (sido_code, sigg_code) in done_gu:
                continue

            # 345kV 전용 API 엔드포인트
            d3 = api_post(
                f"{BASE}/ew/cpct/retrieveCbrOvplsInfo345",
                {
                    "dma_reqParam": {
                        "sido_code": sido_code,
                        "sigg_code": sigg_code,
                        "emd_code": "",
                    }
                },
                headers,
            )
            rows = d3.get("dlt_resultList", []) if d3 else []
            time.sleep(0.25)

            for row in rows:
                all_rows.append(
                    {
                        "시도": sido_nm,
                        "시군구": sigg_nm,
                        "변전소": row.get("S_NM", row.get("SNM", "")),
                        "변전소코드": row.get("S_CD", ""),
                        "345kV_차단기_전체": row.get("B006_TOTAL_BAY", 0),
                        "345kV_차단기_사용중": row.get("B006_USE_BAY_TO", 0),
                        "345kV_차단기_사용예정": row.get("B006_SUBS_BAY", 0),
                        "345kV_차단기_여유": row.get("B006_FUTU_BAY", 0),
                        "_sido_code": sido_code,
                        "_sigg_code": sigg_code,
                    }
                )

            done_gu.add((sido_code, sigg_code))
            if len(done_gu) % 15 == 0:
                pd.DataFrame(all_rows).to_csv(
                    interim_path, index=False, encoding="utf-8-sig"
                )

    bay_cols = [
        "345kV_차단기_전체",
        "345kV_차단기_사용중",
        "345kV_차단기_사용예정",
        "345kV_차단기_여유",
    ]
    return save_and_clean(all_rows, interim_path, final_path, bay_cols)


# ── 유틸리티 함수 ──────────────────────────────────────────────────
def load_interim(interim_path):
    """중간 저장 파일이 있으면 불러오기"""
    if os.path.exists(interim_path):
        prev = pd.read_csv(interim_path)
        done = set(
            zip(prev["_sido_code"].astype(str), prev["_sigg_code"].astype(str))
        )
        print(f"-> 이전 중간 저장 데이터 로드: {len(prev)}행")
        return prev.to_dict("records"), done
    return [], set()


def save_and_clean(all_rows, interim_path, final_path, num_cols):
    """데이터 정제 및 최종 저장"""
    if not all_rows:
        print("수집된 데이터가 없습니다.")
        return None

    df = pd.DataFrame(all_rows).drop(
        columns=["_sido_code", "_sigg_code"], errors="ignore"
    )
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # 수치 데이터가 모두 비어있거나 0인 행 제거
    df = df.dropna(subset=num_cols, how="all")
    df.to_csv(final_path, index=False, encoding="utf-8-sig")

    if os.path.exists(interim_path):
        os.remove(interim_path)

    print(
        f"완료! {final_path} (총 {len(df)}행 / 변전소 {df['변전소'].nunique()}개)"
    )
    return final_path


# ── 5. 종합 데이터셋 통합 머지 ──────────────────────────────────────
def merge_all_datasets():
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 5. 수집된 모든 데이터셋 통합 머지")
    print("=" * 60)

    p_renw = os.path.join(SAVE_DIR, "재생e_연계여유용량.csv")
    p_power = os.path.join(SAVE_DIR, "전력공급_여유용량.csv")
    p_cbr154 = os.path.join(SAVE_DIR, "차단기_여유Bay_154kV.csv")
    p_cbr345 = os.path.join(SAVE_DIR, "차단기_여유Bay_345kV.csv")

    if not os.path.exists(p_renw) or not os.path.exists(p_power):
        print("필수 데이터셋(재생e 또는 전력공급)이 누락되어 병합을 중단합니다.")
        return

    df_renw = pd.read_csv(p_renw)
    df_power = pd.read_csv(p_power)

    # 1. 재생e + 전력공급 병합 (변전소 기준)
    df_merged = pd.merge(
        df_power, df_renw[["변전소", "재생e_여유용량_MW"]], on="변전소", how="left"
    )

    # 2. 154kV 차단기 병합
    if os.path.exists(p_cbr154):
        df_cbr154 = pd.read_csv(p_cbr154)
        c154_cols = [c for c in df_cbr154.columns if "154kV_" in c]
        df_c154_agg = df_cbr154.groupby("변전소")[c154_cols].max().reset_index()
        df_merged = pd.merge(df_merged, df_c154_agg, on="변전소", how="left")

    # 3. 345kV 차단기 병합
    if os.path.exists(p_cbr345):
        df_cbr345 = pd.read_csv(p_cbr345)
        c345_cols = [c for c in df_cbr345.columns if "345kV_" in c]
        df_c345_agg = df_cbr345.groupby("변전소")[c345_cols].max().reset_index()
        df_merged = pd.merge(df_merged, df_c345_agg, on="변전소", how="left")

    out_path = os.path.join(SAVE_DIR, "KEPCO_전력망_종합통합.csv")
    df_merged.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"\n최종 통합 완료! 저장 위치: {out_path}")
    print(f"총 {len(df_merged)}행 / 통합 변전소 수: {df_merged['변전소'].nunique()}개")


if __name__ == "__main__":
    crawl_renw_supply()
    crawl_power_supply()
    crawl_cbr_154()
    crawl_cbr_345()
    merge_all_datasets()