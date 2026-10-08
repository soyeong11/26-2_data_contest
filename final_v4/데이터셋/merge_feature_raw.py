"""
전력 피쳐 + 피쳐에 쓴 원본 열 데이터셋 (2026-10-08)
===================================================
전력_최종피쳐_공유용_v4 (256행) 오른쪽에, 피쳐를 만들 때 실제로 읽은 원본(시군구 집계) 열만 붙인다.
원본 열은 2단계 재집계 wide(크롤링 원본을 256 시군구로 재배정·집계한 표)에서 시군구코드 기준으로 가져옴.

붙이는 열 (USE_GROUPS로 그룹 단위로 켜고 끔)
  점수계산   feature_v4.py가 전력피쳐(용량MW_2029)를 계산할 때 읽은 열
             전력공급229kV_2029년_최대, 전력공급154kV_2029년_최대
  2032참고   feature_v4.py가 장기 참고 시나리오(상세 파일)에 쓴 열
             전력공급229kV_2032년_최대, 전력공급154kV_2032년_최대
  분류판정   step3_분석대상.py가 분석대상/참고등급/제외를 판정할 때 읽은 열
             전력공급229kV_변전소수, 전력공급154kV_변전소수, 재생e연계_변전소수,
             차단기_변전소기준_변전소수, 전력공급154kV_데이터있음
  ※ 345kV 참고 열의 원본(차단기_공급지역기준_345kV여유_합계)은 공유용에 '345kV여유Bay'로 이미 있어 붙이지 않음
  ※ 공유용의 345kV_상위지역공유·개편재배정 열은 DROP_FEATURE_COLS로 뺌
  ※ 민감도 분석에만 쓴 2028·2030년 열은 넣지 않음 (필요하면 USE_GROUPS에 "민감도연도" 추가)

실행 (final_v4 폴더)
  python merge_feature_raw.py

입력  데이터셋/전력_최종피쳐_공유용_v4_*.csv, 데이터셋/전력_시군구wide_256_재집계_*.csv (각각 최신 날짜)
출력  데이터셋/전력_피쳐원본_256_v4_{날짜}.csv     256행 = 피쳐 12열 + 원본 열
      데이터셋/컬럼사전_피쳐원본_v4_{날짜}.csv     열 이름 → 구분·용도·설명

주의
  원본 값은 분석대상이 아닌 지역(참고등급·제외)에도 그대로 있음 (피쳐는 빈칸).
  전력공급154kV_데이터있음 = 0이면 그 시도의 전력공급 0은 '없음'이 아니라 '미수집' (예: 제주)
"""
import glob
import os
import sys
from datetime import datetime
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "데이터셋")
TAG = datetime.now().strftime("%Y%m%d")
OUT = os.path.join(DATA, f"전력_피쳐원본_256_v4_{TAG}.csv")
OUT_DICT = os.path.join(DATA, f"컬럼사전_피쳐원본_v4_{TAG}.csv")

RAW_GROUPS = {   # 그룹: [(열, 설명)]
    "점수계산": [
        ("전력공급229kV_2029년_최대", "2029년 22.9kV 여유용량, 시군구 안 단일 변전소 최댓값 (MW로 해석, 단위 미확인)"),
        ("전력공급154kV_2029년_최대", "2029년 154kV 여유용량, 시군구 안 단일 변전소 최댓값 (MW로 해석, 단위 미확인)"),
    ],
    "2032참고": [
        ("전력공급229kV_2032년_최대", "2032년 22.9kV 여유용량, 단일 변전소 최댓값 (장기 참고 시나리오)"),
        ("전력공급154kV_2032년_최대", "2032년 154kV 여유용량, 단일 변전소 최댓값 (장기 참고 시나리오)"),
    ],
    "분류판정": [
        ("전력공급229kV_변전소수", "22.9kV 전력공급 응답 변전소 수 (0이면 22.9kV 무응답)"),
        ("전력공급154kV_변전소수", "154kV 전력공급 응답 변전소 수 (0이면 154kV 무응답)"),
        ("재생e연계_변전소수", "재생e 연계 응답 변전소 수 (R1 변전소 응답 전무 판정용)"),
        ("차단기_변전소기준_변전소수", "22.9·154kV 차단기 응답 변전소 수 (R1 판정용)"),
        ("전력공급154kV_데이터있음", "시도 전체에서 154kV 전력공급이 1행 이상 수집됨(1) / 0이면 시도 미수집 (R2 판정용)"),
    ],
    "민감도연도": [
        (f"전력공급{v}kV_{y}년_최대", f"{y}년 {v.replace('229', '22.9')}kV 여유용량, 단일 변전소 최댓값 (민감도 분석용)")
        for y in (2028, 2030) for v in ("229", "154")
    ],
}
USE_GROUPS = ["점수계산", "2032참고", "분류판정"]
# 공유용 피쳐 열 중 이 데이터셋에서 뺄 열 (2026-10-08 결정) — 공유용 파일 자체는 그대로 둠
DROP_FEATURE_COLS = ["345kV_상위지역공유", "개편재배정"]

FEATURE_DESC = {
    "시군구코드": "병합 키. 5자리 행정 시군구코드 (기준_시군구256.csv와 코드·순서 동일)",
    "지역코드": "시군구코드와 같은 값 (이전 버전 호환)",
    "시도명": "2026 행정구역 시도명",
    "시군구명": "2026 행정구역 시군구명",
    "분류": "분석대상 / 참고등급 / 제외 (step3_분석대상.py)",
    "전력피쳐": "메인 지표. 용량MW_2029를 분석대상 기준 min-max (0~1, 클수록 유리). 분석대상 외 빈칸",
    "전력순위": "분석대상 내 순위 (1=가장 유리, 동점은 같은 순위)",
    "용량MW_2029": "max(전력공급229kV_2029년_최대, 전력공급154kV_2029년_최대)",
    "결정전압": "용량MW를 준 전압: 154kV / 22.9kV / 없음(0MW). 같으면 154kV",
    "수용가능_0.5GW": "용량MW_2029 ≥ 625 (IT 0.5GW × PUE 1.25). 분석대상만 판정",
    "수용가능_1GW": "용량MW_2029 ≥ 1,250 (IT 1GW × PUE 1.25). 분석대상만 판정",
    "345kV여유Bay": "참고 열(점수 미반영). 원본 차단기_공급지역기준_345kV여유_합계",
}


def latest(pattern):
    files = sorted(glob.glob(os.path.join(DATA, pattern)))
    if not files:
        sys.exit(f"!! 입력 없음: 데이터셋/{pattern}")
    return files[-1]


def main():
    fp, wp = latest("전력_최종피쳐_공유용_v4_*.csv"), latest("전력_시군구wide_256_재집계_*.csv")
    feat = pd.read_csv(fp, encoding="utf-8-sig").drop(columns=DROP_FEATURE_COLS, errors="ignore")
    wide = pd.read_csv(wp, encoding="utf-8-sig")
    print(f"입력: {os.path.basename(fp)}, {os.path.basename(wp)}")
    if len(feat) != 256 or list(feat["시군구코드"]) != list(wide["지역코드"]):
        sys.exit("!! 공유용 시군구코드와 재집계 wide 지역코드의 행 수·값·순서가 다름")

    picked = [(g, c, d) for g in USE_GROUPS for c, d in RAW_GROUPS[g]]
    cols = [c for _, c, _ in picked]
    miss = [c for c in cols if c not in wide.columns]
    if miss:
        sys.exit(f"!! 재집계 wide에 없는 열: {miss}")
    # 재집계 wide의 '시군구코드'는 3자리라 쓰지 않고, 5자리 '지역코드'를 병합 키로 씀
    raw = wide[cols].assign(시군구코드=wide["지역코드"])
    out = feat.merge(raw, on="시군구코드", how="left", validate="1:1")

    # 검증: 행·순서 유지, 원본 값 일치, 피쳐가 원본에서 재현되는지
    assert len(out) == 256 and list(out["시군구코드"]) == list(feat["시군구코드"])
    assert out[cols].reset_index(drop=True).equals(wide[cols].reset_index(drop=True))
    ok = out["분류"].eq("분석대상")
    if "점수계산" in USE_GROUPS:
        mw = out[["전력공급229kV_2029년_최대", "전력공급154kV_2029년_최대"]].max(axis=1)
        assert (mw[ok] == out.loc[ok, "용량MW_2029"]).all(), "용량MW_2029 ≠ max(원본 22.9, 154)"
        assert ((mw[ok] / mw[ok].max()).round(6) == out.loc[ok, "전력피쳐"].round(6)).all(), "전력피쳐 재현 실패"
    if "분류판정" in USE_GROUPS:
        r1 = out[["전력공급229kV_변전소수", "전력공급154kV_변전소수", "재생e연계_변전소수",
                  "차단기_변전소기준_변전소수"]].sum(axis=1) == 0
        assert (r1 == out["분류"].eq("제외")).all(), "R1(제외) 재현 실패"
    print("[검증] 256행·순서 유지 · 원본 값 일치 · 원본으로 용량MW·전력피쳐·제외 판정 재현 → 통과")

    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    rows = [{"열": c, "구분": "피쳐", "용도": "", "설명": FEATURE_DESC.get(c, "")} for c in feat.columns]
    rows += [{"열": c, "구분": "원본(시군구 집계)", "용도": g, "설명": d} for g, c, d in picked]
    pd.DataFrame(rows).to_csv(OUT_DICT, index=False, encoding="utf-8-sig")
    print(f"저장: {os.path.basename(OUT)} ({out.shape[0]}행 x {out.shape[1]}열 = 피쳐 {feat.shape[1]} + 원본 {len(cols)})")
    print(f"저장: {os.path.basename(OUT_DICT)}")


if __name__ == "__main__":
    main()
