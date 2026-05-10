from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import time

app = Flask(__name__)
CORS(app)

DART_API_KEY = os.environ.get("DART_API_KEY", "c0dfa28be5bfbfccf9b738b548aacaa8500acd6f")
DART_BASE = "https://opendart.fss.or.kr/api"

# 종목코드 -> corp_code 매핑 캐시
_corp_map = {}
_corp_map_loaded = False

def load_corp_map():
    global _corp_map, _corp_map_loaded
    if _corp_map_loaded:
        return
    try:
        import zipfile, io, xml.etree.ElementTree as ET
        r = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=30)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_data = z.read("CORPCODE.xml")
        root = ET.fromstring(xml_data)
        for corp in root.findall("list"):
            stock_code = corp.findtext("stock_code", "").strip()
            corp_code = corp.findtext("corp_code", "").strip()
            corp_name = corp.findtext("corp_name", "").strip()
            if stock_code:
                _corp_map[stock_code] = {"corp_code": corp_code, "corp_name": corp_name}
        _corp_map_loaded = True
    except Exception as e:
        print(f"corp_map 로드 오류: {e}")

def get_financial_data(corp_code, year, reprt_code="11011"):
    """DART 재무데이터 조회 (연간: 11011, 1분기: 11013, 반기: 11012, 3분기: 11014)"""
    try:
        r = requests.get(f"{DART_BASE}/fnlttSinglAcntAll.json", params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": "CFS"  # 연결재무제표
        }, timeout=10)
        data = r.json()
        if data.get("status") == "000":
            return data.get("list", [])
        # 연결 없으면 별도재무제표
        r2 = requests.get(f"{DART_BASE}/fnlttSinglAcntAll.json", params={
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": "OFS"
        }, timeout=10)
        data2 = r2.json()
        if data2.get("status") == "000":
            return data2.get("list", [])
    except Exception as e:
        print(f"재무데이터 오류 {corp_code}: {e}")
    return []

def extract_value(items, account_id):
    """재무항목에서 값 추출"""
    for item in items:
        if item.get("account_id") == account_id or item.get("account_nm") == account_id:
            val = item.get("thstrm_amount", "").replace(",", "").strip()
            try:
                return int(val)
            except:
                pass
    return None

def get_revenue(items):
    """매출액 추출 (다양한 계정과목명 대응)"""
    for key in ["ifrs-full_Revenue", "dart_Revenue", "매출액", "수익(매출액)"]:
        v = extract_value(items, key)
        if v is not None:
            return v
    return None

def get_operating_profit(items):
    """영업이익 추출"""
    for key in ["ifrs-full_ProfitLossFromOperatingActivities", "dart_OperatingIncomeLoss", "영업이익"]:
        v = extract_value(items, key)
        if v is not None:
            return v
    return None

def get_net_income(items):
    """당기순이익 추출"""
    for key in ["ifrs-full_ProfitLoss", "dart_ProfitLoss", "당기순이익"]:
        v = extract_value(items, key)
        if v is not None:
            return v
    return None


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/api/screener")
def screener():
    """
    주식 스크리너 메인 API
    query params:
      - market: KOSPI / KOSDAQ / ALL (기본 ALL)
      - sort: per / revenue_growth / pbr / profit_margin (기본 per)
      - limit: 반환 종목 수 (기본 50)
    """
    market = request.args.get("market", "ALL").upper()
    sort_by = request.args.get("sort", "per")
    limit = int(request.args.get("limit", 50))

    load_corp_map()

    # KRX 전종목 리스트 가져오기
    try:
        if market == "KOSPI":
            df = fdr.StockListing("KOSPI")
        elif market == "KOSDAQ":
            df = fdr.StockListing("KOSDAQ")
        else:
            kospi = fdr.StockListing("KOSPI")
            kosdaq = fdr.StockListing("KOSDAQ")
            kospi["Market"] = "KOSPI"
            kosdaq["Market"] = "KOSDAQ"
            df = pd.concat([kospi, kosdaq], ignore_index=True)
    except Exception as e:
        return jsonify({"error": f"종목 리스트 오류: {str(e)}"}), 500

    # 컬럼명 정규화
    df.columns = [c.strip() for c in df.columns]
    code_col = "Code" if "Code" in df.columns else df.columns[0]
    name_col = "Name" if "Name" in df.columns else df.columns[1]

    # 시총 상위 50개만 처리 (메모리 절약)
    if "Marcap" in df.columns:
        df = df.sort_values("Marcap", ascending=False).head(50)
    else:
        df = df.head(50)

    current_year = datetime.now().year
    prev_year = current_year - 1
    prev2_year = current_year - 2

    results = []

    for _, row in df.iterrows():
        stock_code = str(row[code_col]).zfill(6)
        corp_info = _corp_map.get(stock_code)
        if not corp_info:
            continue

        corp_code = corp_info["corp_code"]

        # 당해년도 재무 (없으면 전년도)
        items_cur = get_financial_data(corp_code, prev_year)
        items_prev = get_financial_data(corp_code, prev2_year)

        if not items_cur:
            continue

        revenue_cur = get_revenue(items_cur)
        revenue_prev = get_revenue(items_prev)
        op_profit = get_operating_profit(items_cur)
        net_income = get_net_income(items_cur)

        # 매출 성장률
        revenue_growth = None
        if revenue_cur and revenue_prev and revenue_prev != 0:
            revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)

        # 영업이익률
        profit_margin = None
        if op_profit and revenue_cur and revenue_cur != 0:
            profit_margin = round(op_profit / revenue_cur * 100, 1)

        # 현재 시세 (PER, PBR)
        per = None
        pbr = None
        price = None
        try:
            marcap = float(row.get("Marcap", 0) or 0)
            per_raw = row.get("PER", None)
            pbr_raw = row.get("PBR", None)
            price_raw = row.get("Close", row.get("Price", None))

            if per_raw not in [None, "", "nan"]:
                per = round(float(str(per_raw).replace(",", "")), 1)
            if pbr_raw not in [None, "", "nan"]:
                pbr = round(float(str(pbr_raw).replace(",", "")), 1)
            if price_raw not in [None, "", "nan"]:
                price = int(float(str(price_raw).replace(",", "")))
        except:
            pass

        results.append({
            "code": stock_code,
            "name": row[name_col],
            "market": row.get("Market", market),
            "price": price,
            "per": per,
            "pbr": pbr,
            "revenue": revenue_cur,
            "revenue_prev": revenue_prev,
            "revenue_growth": revenue_growth,
            "operating_profit": op_profit,
            "net_income": net_income,
            "profit_margin": profit_margin,
            "marcap": int(float(row.get("Marcap", 0) or 0)),
        })

        time.sleep(0.05)  # DART API 요청 간격

    # 정렬
    if sort_by == "per":
        results = [r for r in results if r["per"] and r["per"] > 0]
        results.sort(key=lambda x: x["per"])
    elif sort_by == "revenue_growth":
        results = [r for r in results if r["revenue_growth"] is not None]
        results.sort(key=lambda x: x["revenue_growth"], reverse=True)
    elif sort_by == "pbr":
        results = [r for r in results if r["pbr"] and r["pbr"] > 0]
        results.sort(key=lambda x: x["pbr"])
    elif sort_by == "profit_margin":
        results = [r for r in results if r["profit_margin"] is not None]
        results.sort(key=lambda x: x["profit_margin"], reverse=True)

    return jsonify({
        "status": "ok",
        "count": len(results[:limit]),
        "sort": sort_by,
        "market": market,
        "updated": prev_year,
        "data": results[:limit]
    })


@app.route("/api/stock/<code>")
def stock_detail(code):
    """종목 상세 정보"""
    load_corp_map()
    stock_code = code.zfill(6)
    corp_info = _corp_map.get(stock_code)
    if not corp_info:
        return jsonify({"error": "종목 없음"}), 404

    corp_code = corp_info["corp_code"]
    prev_year = datetime.now().year - 1

    # 최근 3년 재무
    years_data = []
    for y in [prev_year - 2, prev_year - 1, prev_year]:
        items = get_financial_data(corp_code, y)
        if items:
            years_data.append({
                "year": y,
                "revenue": get_revenue(items),
                "operating_profit": get_operating_profit(items),
                "net_income": get_net_income(items),
            })

    # 주가 차트 (1년)
    try:
        price_df = fdr.DataReader(stock_code, datetime.now() - timedelta(days=365))
        price_history = [
            {"date": str(d.date()), "close": int(r["Close"])}
            for d, r in price_df.iterrows()
        ][-60:]  # 최근 60거래일
    except:
        price_history = []

    return jsonify({
        "code": stock_code,
        "name": corp_info["corp_name"],
        "corp_code": corp_code,
        "financials": years_data,
        "price_history": price_history,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
