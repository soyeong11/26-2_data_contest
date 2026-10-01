"""
진단 전용 (파일 생성/수정 없음) — energy 네임스페이스(전력공급 API)가
부산/대구/울산/세종/경북/경남/제주를 실제로 돌려주는지 직접 확인.

사용: kepco_crawler.py와 같은 폴더에 넣고
      python diag_energy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kepco_crawler import headers_for, get_sido_energy, get_sigg_energy  # noqa: E402

TARGETS = {"부산", "대구", "울산", "세종", "경북", "경남", "제주", "경상북도", "경상남도", "제주특별자치도", "세종특별자치시"}

headers = headers_for("EWM104D04")
sido_list = get_sido_energy(headers)
print(f"selectDo 응답: 총 {len(sido_list)}개 시도")
for s in sido_list:
    print(f"  {s['NSDIP_ALL_ADDR_CD']}  {s['ADDR_NM']}")

found_names = {s["ADDR_NM"] for s in sido_list}
missing_from_do = [t for t in TARGETS if not any(t in n for n in found_names)]
print(f"\nselectDo 목록에 아예 안 보이는 대상: {missing_from_do or '없음 (전부 목록엔 있음)'}")

print("\n--- 문제 시도들의 selectGu(시군구) 응답 직접 확인 ---")
for s in sido_list:
    nm = s["ADDR_NM"]
    if any(t in nm for t in TARGETS):
        gu = get_sigg_energy(headers, s["NSDIP_ALL_ADDR_CD"])
        print(f"  {nm} ({s['NSDIP_ALL_ADDR_CD']}): 시군구 {len(gu)}개" +
              (f"  예: {gu[0]}" if gu else "  <- 비어 있음"))