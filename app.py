from flask import Flask, jsonify, request
from flask_cors import CORS
import FinanceDataReader as fdr
import pandas as pd
import requests
import os
from datetime import datetime

app = Flask(__name__)
CORS(app, origins="*")

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
    elif score >= 2: score = 3
    elif score >= 1: return 2
    else: return 1
    return score

def get_recommendation(stars):
    if stars >= 5: return {"label": "강력추천", "color": "green", "icon": "🌟"}
    elif stars >= 4: return {"label": "추천", "color": "blue", "icon": "⭐"}
    elif stars >= 3: return {"label": "보통", "color": "gray", "icon": "➖"}
    else: return {"label": "비추천", "color": "red", "icon": "❌"}

SECTOR_MAP = {
    "반도체/IT": ["반도체", "전자", "디스플레이", "IT", "전기전자"],
    "바이오/제약": ["제약", "바이오", "의약품", "의료"],
    "건설/부동산": ["건설", "부동산", "건축"],
    "음식/식품": ["음식료", "식품", "음료", "제과"],
    "금융/은행": ["은행", "금융", "보험", "증권"],
    "자동차": ["자동차", "운수장비"],
    "화학/소재": ["화학", "소재", "정유"],
    "엔터/미디어": ["엔터", "미디어", "방송", "게임"],
    "유통/소비재": ["유통", "도소매", "소비재"],
    "에너지": ["에너지", "전기", "가스"],
    "운송/물류": ["운송", "항공", "해운"],
    "통신": ["통신"],
    "철강/금속": ["철강", "금속"],
    "방산": ["방산", "항공우주"],
    "2차전지": ["2차전지", "배터리"],
}

def get_dart_financials_bulk(year):
    """DART 전체 재무데이터 한번에 받기"""
    results = {}
    try:
        # 주요 계정과목만 조회
        for account in ["매출액", "영업이익"]:
            r = requests.get(f"{DART_BASE}/fnlttMultiAcnt.json", params={
                "crtfc_key": DART_API_KEY,
                "bsns_year": str(year),
                "reprt_code": "11011",
                "fs_div": "CFS"
            }, timeout=20)
            data = r.json()
            if data.get("status") == "000":
                for item in data.get("list", []):
                    code = item.get("stock_code", "").strip()
                    if not code: continue
                    if code not in results:
                        results[code] = {}
                    acct = item.get("account_nm", "")
                    val = item.get("thstrm_amount", "").replace(",", "").strip()
                    try:
                        val = int(val)
                    except:
                        continue
                    if "매출" in acct:
                        results[code]["revenue"] = val
                    elif "영업이익" in acct:
                        results[code]["operating_profit"] = val
    except Exception as e:
        print(f"DART 벌크 오류: {e}")
    return results

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

@app.route("/api/screener")
def screener():
    market = request.args.get("market", "ALL").upper()
    sort_by = request.args.get("sort", "per")
    limit = int(request.args.get("limit", 50))
    sector = request.args.get("sector", "")
    search = request.args.get("search", "").strip()

    # KRX 종목 리스트
    try:
        if market == "KOSPI":
            df = fdr.StockListing("KOSPI"); df["Market"] = "KOSPI"
        elif market == "KOSDAQ":
            df = fdr.StockListing("KOSDAQ"); df["Market"] = "KOSDAQ"
        else:
            k1 = fdr.StockListing("KOSPI"); k1["Market"] = "KOSPI"
            k2 = fdr.StockListing("KOSDAQ"); k2["Market"] = "KOSDAQ"
            df = pd.concat([k1, k2], ignore_index=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    df.columns = [c.strip() for c in df.columns]

    # DART 재무데이터 한번에
    prev_year = datetime.now().year - 1
    prev2_year = prev_year - 1
    fin_cur = get_dart_financials_bulk(prev_year)
    fin_prev = get_dart_financials_bulk(prev2_year)

    def to_float(v):
        try: return float(str(v).replace(",", ""))
        except: return None

    results = []
    for _, row in df.iterrows():
        try:
            code = str(row.get("Code", "")).zfill(6)
            name = str(row.get("Name", ""))
            mkt = str(row.get("Market", market))
            industry = str(row.get("Industry", row.get("Sector", "")))

            if not name or name == "nan": continue
            if search and search.lower() not in name.lower() and search not in code: continue
            if sector:
                keywords = SECTOR_MAP.get(sector, [])
                if not any(k in industry for k in keywords): continue

            per = to_float(row.get("PER"))
            pbr = to_float(row.get("PBR"))
            price = to_float(row.get("Close", row.get("Adj Close")))
            marcap = to_float(row.get("Marcap"))

            per = round(per, 1) if per and 0 < per < 500 else None
            pbr = round(pbr, 1) if pbr and 0 < pbr < 100 else None

            # DART 재무
            fin = fin_cur.get(code, {})
            fin_p = fin_prev.get(code, {})
            revenue_cur = fin.get("revenue")
            revenue_prev = fin_p.get("revenue")
            op_profit = fin.get("operating_profit")

            revenue_growth = None
            profit_margin = None
            if revenue_cur and revenue_prev and revenue_prev != 0:
                revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
            if op_profit and revenue_cur and revenue_cur != 0:
                profit_margin = round(op_profit / revenue_cur * 100, 1)

            stars = calc_stars(per, pbr, revenue_growth, profit_margin)
            rec = get_recommendation(stars)

            results.append({
                "code": code, "name": name, "market": mkt, "industry": industry,
                "price": int(price) if price else None,
                "per": per, "pbr": pbr,
                "revenue": revenue_cur, "revenue_growth": revenue_growth,
                "operating_profit": op_profit, "profit_margin": profit_margin,
                "marcap": int(marcap) if marcap else None,
                "stars": stars, "recommendation": rec,
            })
        except: continue

    # 정렬
    if sort_by == "per":
        results = [r for r in results if r["per"]]
        results.sort(key=lambda x: x["per"])
    elif sort_by == "revenue_growth":
        results = [r for r in results if r["revenue_growth"] is not None]
        results.sort(key=lambda x: x["revenue_growth"], reverse=True)
    elif sort_by == "pbr":
        results = [r for r in results if r["pbr"]]
        results.sort(key=lambda x: x["pbr"])
    elif sort_by == "profit_margin":
        results = [r for r in results if r["profit_margin"] is not None]
        results.sort(key=lambda x: x["profit_margin"], reverse=True)
    elif sort_by == "stars":
        results.sort(key=lambda x: x["stars"], reverse=True)

    pers = [r["per"] for r in results if r["per"]]
    growths = [r["revenue_growth"] for r in results if r["revenue_growth"] is not None]

    return jsonify({
        "status": "ok",
        "count": len(results[:limit]),
        "sort": sort_by, "market": market,
        "updated": prev_year,
        "avg_per": round(sum(pers)/len(pers), 1) if pers else None,
        "avg_growth": round(sum(growths)/len(growths), 1) if growths else None,
        "data": results[:limit]
    })

@app.route("/api/stock/<code>")
def stock_detail(code):
    code = code.zfill(6)
    prev_year = datetime.now().year - 1
    years_data = []
    for y in [prev_year-2, prev_year-1, prev_year]:
        fin = get_dart_financials_bulk(y)
        d = fin.get(code, {})
        rev = d.get("revenue")
        op = d.get("operating_profit")
        if rev or op:
            years_data.append({
                "year": y, "revenue": rev, "operating_profit": op,
                "profit_margin": round(op/rev*100, 1) if op and rev else None
            })
    try:
        price_df = fdr.DataReader(code, '2024-01-01')
        price_history = [{"date": str(d.date()), "close": int(r["Close"])} for d, r in price_df.tail(60).iterrows()]
        high_52w = int(price_df["Close"].max())
        low_52w = int(price_df["Close"].min())
    except:
        price_history = []; high_52w = low_52w = None

    return jsonify({
        "code": code, "financials": years_data,
        "price_history": price_history,
        "high_52w": high_52w, "low_52w": low_52w,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
