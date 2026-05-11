import FinanceDataReader as fdr
import pandas as pd
import json
import os
from datetime import datetime

def calc_stars(per, pbr):
    score = 0
    if per:
        if per < 10: score += 2
        elif per < 15: score += 1
    if pbr:
        if pbr < 1: score += 2
        elif pbr < 1.5: score += 1
    if score >= 4: return 5
    elif score >= 3: return 4
    elif score >= 2: return 3
    elif score >= 1: return 2
    else: return 1

def get_recommendation(stars):
    if stars >= 5: return {"label": "강력추천", "color": "green", "icon": "🌟"}
    elif stars >= 4: return {"label": "추천", "color": "blue", "icon": "⭐"}
    elif stars >= 3: return {"label": "보통", "color": "gray", "icon": "➖"}
    else: return {"label": "비추천", "color": "red", "icon": "❌"}

def main():
    print("전종목 데이터 수집 시작...")

    k1 = fdr.StockListing("KOSPI"); k1["Market"] = "KOSPI"
    k2 = fdr.StockListing("KOSDAQ"); k2["Market"] = "KOSDAQ"
    df = pd.concat([k1, k2], ignore_index=True)
    df.columns = [c.strip() for c in df.columns]
    print(f"전체 종목: {len(df)}개")

    def to_float(v):
        try: return float(str(v).replace(",", "").strip())
        except: return None

    industry_col = next((c for c in ["Industry", "Sector", "업종"] if c in df.columns), None)
    print(f"업종 컬럼: {industry_col}")
    print(f"전체 컬럼: {list(df.columns)}")

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
            eps = to_float(row.get("EPS"))
            price = to_float(row.get("Close", row.get("Adj Close")))
            marcap = to_float(row.get("Marcap"))

            per = round(per, 1) if per and 0 < per < 500 else None
            pbr = round(pbr, 1) if pbr and 0 < pbr < 100 else None

            stars = calc_stars(per, pbr)

            stocks.append({
                "code": code,
                "name": name,
                "market": mkt,
                "industry": industry,
                "price": int(price) if price else None,
                "per": per,
                "pbr": pbr,
                "eps": int(eps) if eps else None,
                "revenue": None,
                "revenue_growth": None,
                "operating_profit": None,
                "profit_margin": None,
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

    print("저장 완료!")

if __name__ == "__main__":
    main()
