import requests
import json
import os
from datetime import datetime

# 한국 주식 전체 수집 스크립트
def get_kospi_stocks():
    url = "https://finance.naver.com/api/sise/etfItemList.nhn"
    headers = {"User-Agent": "Mozilla/5.0"}
    stocks = []
    try:
        # KOSPI 주요 종목 리스트
        kospi_codes = [
            "005930", "000660", "051910", "035420", "005380",
            "000270", "068270", "105560", "055550", "035720",
            "096770", "003550", "017670", "030200", "032830",
            "086790", "316140", "009150", "018260", "011170",
            "010130", "028260", "012330", "066570", "024110",
            "003490", "000810", "011200", "010950", "033780"
        ]
        for code in kospi_codes:
            try:
                detail_url = f"https://finance.naver.com/item/main.nhn?code={code}"
                r = requests.get(detail_url, headers=headers, timeout=5)
                stocks.append({"code": code, "market": "KOSPI"})
            except:
                pass
    except Exception as e:
        print(f"KOSPI 수집 오류: {e}")
    return stocks

def get_kosdaq_stocks():
    stocks = []
    try:
        kosdaq_codes = [
            "247540", "086520", "091990", "196170", "214150",
            "145020", "112040", "357780", "041510", "263750",
            "095340", "078600", "067630", "141080", "039030",
            "122870", "293490", "237690", "328130", "048410"
        ]
        for code in kosdaq_codes:
            stocks.append({"code": code, "market": "KOSDAQ"})
    except Exception as e:
        print(f"KOSDAQ 수집 오류: {e}")
    return stocks

def fetch_stock_data(code):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://finance.naver.com/item/sise.nhn?code={code}"
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'euc-kr'
        return r.text
    except Exception as e:
        print(f"종목 {code} 데이터 수집 오류: {e}")
        return None

def main():
    print(f"주식 데이터 수집 시작: {datetime.now()}")
    
    all_stocks = []
    all_stocks.extend(get_kospi_stocks())
    all_stocks.extend(get_kosdaq_stocks())
    
    print(f"총 {len(all_stocks)}개 종목 수집 완료")
    
    # 결과 저장
    os.makedirs('data', exist_ok=True)
    with open('data/stocks_list.json', 'w', encoding='utf-8') as f:
        json.dump({
            'updated_at': datetime.now().isoformat(),
            'total_count': len(all_stocks),
            'stocks': all_stocks
        }, f, ensure_ascii=False, indent=2)
    
    print(f"데이터 저장 완료: data/stocks_list.json")
    print(f"수집 완료: {datetime.now()}")

if __name__ == '__main__':
    main()
