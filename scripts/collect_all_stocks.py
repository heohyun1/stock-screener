import requests
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import time

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

def get_krx_stock_info():
    """KRX 전종목 기본정보 (PER, PBR, 시가총액)"""
    headers = {
        "Referer": "http://data.krx.co.kr",
        "User-Agent": "Mozilla/5.0"
    }
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    
    stocks = {}
    
    for mkt_id, mkt_name in [("STK", "KOSPI"), ("KSQ", "KOSDAQ")]:
        try:
            # 오늘 날짜
            today = datetime.now().strftime("%Y%m%d")
            
            r = requests.post(url, data={
                "bld": "dbms/MDC/STAT/standard/MDCSTAT03501",
                "mktId": mkt_id,
                "trdDd": today,
                "share": "1",
                "money": "1",
                "csvxls_isNo": "false"
            }, headers=headers, timeout=30)
            
            data = r.json()
            items = data.get("OutBlock_1", [])
            print(f"{mkt_name}: {len(items)}개 종목")
            
            for item in items:
                code = str(item.get("ISU_SRT_CD", "")).zfill(6)
                if not code: continue
                
                def to_float(v):
                    try: return float(str(v).replace(",", "").strip())
                    except: return None
                
                per = to_float(item.get("PER"))
                pbr = to_float(item.get("PBR"))
                price = to_float(item.get("TDD_CLSPRC"))
                marcap = to_float(item.get("MKTCAP"))
                
                stocks[code] = {
                    "code": code,
                    "name": str(item.get("ISU_ABBRV", "")),
                    "market": mkt_name,
                    "industry": str(item.get("IDX_IND_NM", "")),
                    "price": int(price) if price else None,
                    "per": round(per, 1) if per and 0 < per < 500 else None,
                    "pbr": round(pbr, 1) if pbr and 0 < pbr < 100 else None,
                    "marcap": int(marcap) if marcap else None,
                }
        except Exception as e:
            print(f"{mkt_name} 오류: {e}")
    
    return stocks

def get_krx_financials():
    """KRX 전종목 재무데이터 (매출, 영업이익)"""
    headers = {
        "Referer": "http://data.krx.co.kr",
        "User-Agent": "Mozilla/5.0"
    }
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    
    financials = {}
    
    # 연간 재무데이터
    for year in [str(datetime.now().year - 1), str(datetime.now().year - 2)]:
        try:
            r = requests.post(url, data={
                "bld": "dbms/MDC/STAT/standard/MDCSTAT03701",
                "searchType": "1",
                "mktId": "ALL",
                "secugrpId": "STMFND",
                "year": year,
                "money": "1",
                "csvxls_isNo": "false"
            }, headers=headers, timeout=30)
            
            data = r.json()
            items = data.get("OutBlock_1", [])
            print(f"{year}년 재무데이터: {len(items)}개")
            
            for item in items:
                code = str(item.get("ISU_SRT_CD", "")).zfill(6)
                if not code: continue
                
                def to_float(v):
                    try: return float(str(v).replace(",", "").strip())
                    except: return None
                
                revenue = to_float(item.get("SALE_AMT"))
                op_profit = to_float(item.get("BSOP_PROFT"))
                
                if code not in financials:
                    financials[code] = {}
                financials[code][year] = {
                    "revenue": int(revenue) if revenue else None,
                    "operating_profit": int(op_profit) if op_profit else None,
                }
        except Exception as e:
            print(f"{year}년 재무 오류: {e}")
    
    return financials

def main():
    print("KRX 전종목 데이터 수집 시작...")
    
    # 종목 기본정보
    stocks = get_krx_stock_info()
    print(f"총 {len(stocks)}개 종목 수집")
    
    # 재무데이터
    financials = get_krx_financials()
    print(f"재무데이터 {len(financials)}개 종목")
    
    prev_year = str(datetime.now().year - 1)
    prev2_year = str(datetime.now().year - 2)
    
    # 데이터 합치기
    result = []
    for code, stock in stocks.items():
        fin_cur = financials.get(code, {}).get(prev_year, {})
        fin_prev = financials.get(code, {}).get(prev2_year, {})
        
        revenue_cur = fin_cur.get("revenue")
        revenue_prev = fin_prev.get("revenue")
        op_profit = fin_cur.get("operating_profit")
        
        revenue_growth = None
        profit_margin = None
        
        if revenue_cur and revenue_prev and revenue_prev != 0:
            revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
        if op_profit and revenue_cur and revenue_cur != 0:
            profit_margin = round(op_profit / revenue_cur * 100, 1)
        
        stars = calc_stars(stock.get("per"), stock.get("pbr"), revenue_growth, profit_margin)
        
        result.append({
            **stock,
            "revenue": revenue_cur,
            "revenue_growth": revenue_growth,
            "operating_profit": op_profit,
            "profit_margin": profit_margin,
            "stars": stars,
            "recommendation": get_recommendation(stars),
        })
    
    os.makedirs("data", exist_ok=True)
    output = {
        "updated": datetime.now().isoformat(),
        "count": len(result),
        "stocks": result
    }
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)
    
    print(f"완료! {len(result)}개 종목 저장됨")

if __name__ == "__main__":
    main()
