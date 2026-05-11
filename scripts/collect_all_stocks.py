import FinanceDataReader as fdr
import pandas as pd
import requests
import json
import os
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime

DART_API_KEY = os.environ.get("DART_API_KEY", "c0dfa28be5bfbfccf9b738b548aacaa8500acd6f")
DART_BASE = "https://opendart.fss.or.kr/api"

def calc_stars(per, pbr, revenue_growth, profit_margin):
    score = 0
    if per:
        if per < 10: score += 2
        elif per < 15: score += 1
    if pbr:
        if pbr < 1: score += 2
        elif pbr < 1.5: score += 1
    if revenue_growth is not None:
        if revenue_growth >= 20: score += 2
        elif revenue_growth >= 10: score += 1
        elif revenue_growth < 0: score -= 1
    if profit_margin is not None:
        if profit_margin >= 15: score += 2
        elif profit_margin >= 8: score += 1
        elif profit_margin < 0: score -= 1
    if score >= 6: return 5
    elif score >= 4: return 4
    elif score >= 2: return 3
    elif score >= 1: return 2
    else: return 1

def get_recommendation(stars):
    if stars >= 5: return {"label": "강력추천", "color": "green", "icon": "🌟"}
    elif stars >= 4: return {"label": "추천", "color": "blue", "icon": "⭐"}
    elif stars >= 3: return {"label": "보통", "color": "gray", "icon": "➖"}
    else: return {"label": "비추천", "color": "red", "icon": "❌"}

def load_corp_map():
    corp_map = {}
    try:
        r = requests.get(f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": DART_API_KEY}, timeout=30)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_data = z.read("CORPCODE.xml")
        root = ET.fromstring(xml_data)
        for corp in root.findall("list"):
            stock_code = corp.findtext("stock_code", "").strip()
            corp_code = corp.findtext("corp_code", "").strip()
            if stock_code:
                corp_map[stock_code] = corp_code
        print(f"corp_map: {len(corp_map)}개")
    except Exception as e:
        print(f"corp_map 오류: {e}")
    return corp_map

def get_dart_financials_bulk(corp_codes_list, year):
    """100개씩 묶어서 DART 재무데이터 조회"""
    all_data = {}
    total_batches = len(corp_codes_list)
    
    for i, batch in enumerate(corp_codes_list):
        try:
            corp_code_str = ",".join(batch)
            r = requests.get(f"{DART_BASE}/fnlttMultiAcnt.json", params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code_str,
                "bsns_year": str(year),
                "reprt_code": "11011",
            }, timeout=30)
            data = r.json()
            if data.get("status") == "000":
                for item in data.get("list", []):
                    code = str(item.get("stock_code", "")).strip().zfill(6)
                    if not code or code == "000000": continue
                    acct = item.get("account_nm", "")
                    val_str = item.get("thstrm_amount", "").replace(",", "").strip()
                    try:
                        val = int(val_str)
                    except:
                        continue
                    if code not in all_data:
                        all_data[code] = {}
                    if any(k in acct for k in ["매출액", "수익(매출액)"]) and "revenue" not in all_data[code]:
                        all_data[code]["revenue"] = val
                    elif "영업이익" in acct and "영업이익률" not in acct and "operating_profit" not in all_data[code]:
                        all_data[code]["operating_profit"] = val
            if (i+1) % 10 == 0:
                print(f"  배치 {i+1}/{total_batches} 완료 ({len(all_data)}개 누적)")
        except Exception as e:
            print(f"배치 {i+1} 오류: {e}")
    
    return all_data

def main():
    print("전종목 데이터 수집 시작...")

    # FDR 전종목
    k1 = fdr.StockListing("KOSPI"); k1["Market"] = "KOSPI"
    k2 = fdr.StockListing("KOSDAQ"); k2["Market"] = "KOSDAQ"
    df = pd.concat([k1, k2], ignore_index=True)
    df.columns = [c.strip() for c in df.columns]
    print(f"전체 종목: {len(df)}개")

    # corp_map 로드
    corp_map = load_corp_map()

    # corp_code 100개씩 배치 만들기
    def to_float(v):
        try: return float(str(v).replace(",", "").strip())
        except: return None

    industry_col = next((c for c in ["Industry", "Sector", "업종"] if c in df.columns), None)

    # 전체 corp_code 리스트
    all_corp_codes = []
    for _, row in df.iterrows():
        code = str(row.get("Code", "")).zfill(6)
        corp_code = corp_map.get(code)
        if corp_code:
            all_corp_codes.append(corp_code)

    # 100개씩 배치
    batch_size = 100
    batches = [all_corp_codes[i:i+batch_size] for i in range(0, len(all_corp_codes), batch_size)]
    print(f"총 {len(batches)}개 배치로 처리")

    # DART 재무데이터 수집
    prev_year = datetime.now().year - 1
    prev2_year = prev_year - 1

    print(f"{prev_year}년 재무데이터 수집 중...")
    fin_cur = get_dart_financials_bulk(batches, prev_year)
    print(f"{prev_year}년 완료: {len(fin_cur)}개")

    print(f"{prev2_year}년 재무데이터 수집 중...")
    fin_prev = get_dart_financials_bulk(batches, prev2_year)
    print(f"{prev2_year}년 완료: {len(fin_prev)}개")

    # 데이터 합치기
    stocks = []
    for _, row in df.iterrows():
        try:
            code = str(row.get("Code", "")).zfill(6)
            name = str(row.get("Name", ""))
            mkt = str(row.get("Market", ""))
            industry = str(row.get(industry_col, "")) if industry_col else ""

            if not name or name == "nan": continue

            per = to_float(row.get("PER"))
            pbr = to_float(row.get("PBR"))
            price = to_float(row.get("Close", row.get("Adj Close")))
            marcap = to_float(row.get("Marcap"))

            per = round(per, 1) if per and 0 < per < 500 else None
            pbr = round(pbr, 1) if pbr and 0 < pbr < 100 else None

            fin = fin_cur.get(code, {})
            fin_p = fin_prev.get(code, {})
            revenue_cur = fin.get("revenue")
            revenue_prev = fin_p.get("revenue")
            op_profit = fin.get("operating_profit")

            revenue_growth = profit_margin = None
            if revenue_cur and revenue_prev and revenue_prev != 0:
                revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
            if op_profit and revenue_cur and revenue_cur != 0:
                profit_margin = round(op_profit / revenue_cur * 100, 1)

            stars = calc_stars(per, pbr, revenue_growth, profit_margin)

            stocks.append({
                "code": code, "name": name, "market": mkt, "industry": industry,
                "price": int(price) if price else None,
                "per": per, "pbr": pbr,
                "revenue": revenue_cur,
                "revenue_growth": revenue_growth,
                "operating_profit": op_profit,
                "profit_margin": profit_margin,
                "marcap": int(marcap) if marcap else None,
                "stars": stars,
                "recommendation": get_recommendation(stars),
            })
        except:
            continue

    print(f"최종 {len(stocks)}개 종목")

    os.makedirs("data", exist_ok=True)
    output = {
        "updated": datetime.now().isoformat(),
        "count": len(stocks),
        "stocks": stocks
    }
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    print("완료!")

if __name__ == "__main__":
    main()
