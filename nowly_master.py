import os
import time
import datetime
import requests
import xml.etree.ElementTree as ET
import google.generativeai as genai
from supabase import create_client, Client

# 1. 환경변수 로드 (깃허브 Secrets에서 자동으로 가져옵니다)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 2. 클라이언트 세팅
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

# 혜자 모델 적용
model = genai.GenerativeModel('gemini-flash-latest')

# ─── 데이터 크롤링 영역 ───
def get_google_trends():
    url = "https://trends.google.com/trending/rss?geo=KR"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        root = ET.fromstring(res.text)
        return {item.find('title').text.strip(): i + 1 for i, item in enumerate(root.findall('.//item')[:10])}
    except:
        return {}

def get_signal_trends():
    url = "https://api.signal.bz/news/realtime"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        signal_dict = {}
        for i, item in enumerate(res.json().get("top10", [])):
            raw_keyword = item.get("keyword", "").strip()
            short_keyword = raw_keyword.split(' ')[0] if ' ' in raw_keyword else raw_keyword
            if short_keyword not in signal_dict:
                signal_dict[short_keyword] = i + 1
        return signal_dict
    except:
        return {}

def create_nowly_ranking():
    google_data = get_google_trends()
    signal_data = get_signal_trends()
    scoring_board = []
    processed_signal_words = set()

    for g_word, g_rank in google_data.items():
        g_score = 11 - g_rank
        matched = False
        for s_word, s_rank in signal_data.items():
            clean_g = g_word.replace(" ", "").lower()
            clean_s = s_word.replace(" ", "").lower()
            if clean_g in clean_s or clean_s in clean_g:
                s_score = 11 - s_rank
                best_title = g_word if len(g_word) <= len(s_word) else s_word
                scoring_board.append({"title": best_title, "score": g_score + s_score + 100, "source": "통합🔥"})
                processed_signal_words.add(s_word)
                matched = True
                break
        if not matched:
            scoring_board.append({"title": g_word, "score": g_score, "source": "구글"})

    for s_word, s_rank in signal_data.items():
        if s_word not in processed_signal_words:
            scoring_board.append({"title": s_word, "score": 11 - s_rank, "source": "시그널"})

    scoring_board.sort(key=lambda x: x['score'], reverse=True)
    final_trends = []
    seen_titles = set()
    for item in scoring_board:
        check_title = item["title"].replace(" ", "").lower()
        if check_title not in seen_titles:
            seen_titles.add(check_title)
            rank = len(final_trends) + 1
            final_trends.append({"id": rank, "rank": rank, "title": item["title"], "volume": item["source"]})
        if len(final_trends) == 10:
            break
    return final_trends

# 🚨 수정된 위키백과 정보 추출 (확실하게 가져옵니다!)
def get_wiki_summary(keyword):
    # 띄어쓰기가 있다면 가장 앞 단어만 사용하여 검색 확률 상승
    search_term = keyword.split(' ')[0] if ' ' in keyword else keyword
    url = f"https://ko.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(search_term)}"

    try:
        # 위키백과 봇 차단 방지용 신분증 제시
        headers = {'User-Agent': 'NowlyBot/1.0 (admin@nowly.kr)'}
        res = requests.get(url, headers=headers, timeout=5)

        if res.status_code == 200:
            data = res.json()
            return data.get('extract', data.get('description', '위키백과 본문 요약을 찾을 수 없습니다.'))
        elif res.status_code == 404:
            return f"'{search_term}'에 대한 위키백과 문서를 찾을 수 없습니다."
        else:
            return "위키백과 정보를 불러오는 중 서버 오류가 발생했습니다."
    except Exception as e:
        return "위키백과와 통신 중 오류가 발생했습니다."

# 구글 뉴스에서 실시간 헤드라인 3개 훔쳐오기 (AI 정답지 용도)
def get_news_headlines(keyword):
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(keyword)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.text)
        headlines = [item.find('title').text for item in root.findall('.//item')[:3]]
        return " / ".join(headlines) if headlines else "관련 뉴스 없음"
    except:
        return "뉴스 검색 실패"

# 제미나이 하이브리드 일괄 요약 (광속 처리)
def get_batch_ai_summaries(keywords):
    if not keywords:
        return {}

    keyword_context = ""
    for k in keywords:
        headlines = get_news_headlines(k)
        keyword_context += f"키워드: {k} (최신뉴스: {headlines})\n"

    prompt = f"""
    다음은 현재 한국의 실시간 검색어와, 방금 긁어온 최신 뉴스 헤드라인들입니다.
    {keyword_context}

    [분석 지침 - 반드시 지킬 것]
    1. 우선 제공된 '최신뉴스'를 바탕으로 이슈의 원인을 파악하십시오.
    2. 만약 뉴스가 없거나("관련 뉴스 없음"), 뉴스로 설명되지 않는 커뮤니티 밈, 유튜브, 인터넷 방송 관련 바이럴 이슈라면, 당신이 가진 최신 지식을 총동원하여 '진짜 유행하는 이유'를 명확히 추론하십시오.
    3. 각 키워드당 오직 '딱 한 문장'으로만 요약하십시오.
    4. 별표, 샵, 대괄호 등 특수문자는 절대 사용하지 말고 존댓말로 작성하십시오.

    출력 예시:
    {keywords[0]}: 뉴스에 따르면 어쩌고 저쩌고 해서 화제가 되고 있습니다.
    """

    summary_dict = {}
    try:
        response = model.generate_content(prompt)
        lines = response.text.strip().replace('*', '').replace('#', '').split('\n')
        for line in lines:
            if ':' in line:
                parts = line.split(':', 1)
                k_word = parts[0].strip()
                s_text = parts[1].strip()
                summary_dict[k_word] = s_text
        return summary_dict
    except Exception as e:
        print(f"\n[!] 일괄 요약 에러: {e}\n", flush=True)
        return {}

# ─── 메인 프로세스 및 데이터베이스 연동 ───
def process_trends():
    print(f"\n🚀 [{datetime.datetime.now()}] Now.ly 실시간 크롤링 (풀옵션 장착) 시작!", flush=True)
    current_trends = create_nowly_ranking()

    if not current_trends:
        print("수집된 트렌드 데이터가 없습니다.", flush=True)
        return

    try:
        supabase.table("google_trends").update({"rank": 99}).neq("rank", 99).execute()
    except Exception as e:
        pass

    needs_ai_keywords = []
    trend_data_list = []

    for item in current_trends:
        keyword = item['title']
        existing_data = supabase.table("google_trends").select("*").eq("title", keyword).execute()

        should_update_ai = True
        saved_ai_summary = "최신 트렌드를 분석하여 요약 중입니다."
        saved_wiki_content = ""

        if existing_data.data:
            row = existing_data.data[0]
            if row.get('updated_at'):
                time_str = row['updated_at']
                time_str = time_str.split('.')[0] + '+00:00' if '.' in time_str else time_str.replace('Z', '+00:00')
                last_updated = datetime.datetime.fromisoformat(time_str)
                now = datetime.datetime.now(datetime.timezone.utc)

                # 1시간 이내에 수집한 데이터면 캐시 사용
                if row.get('summary') and (now - last_updated).total_seconds() < 3600:
                    if "요약 중입니다" not in row['summary']:
                        should_update_ai = False
                        saved_ai_summary = row['summary']
                        saved_wiki_content = row.get('wiki_content', '')
                        print(f"✅ [{keyword}] 기존 캐시 사용 (위키 포함)", flush=True)

        if should_update_ai:
            needs_ai_keywords.append(keyword)
            # 🚨 캐시가 만료되었거나 새 키워드면 위키백과를 무조건 새로 긁어옵니다.
            saved_wiki_content = get_wiki_summary(keyword)

        trend_data_list.append({
            "rank": item['rank'],
            "title": keyword,
            "volume": item['volume'],
            "summary": saved_ai_summary,
            "wiki_content": saved_wiki_content,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

    if needs_ai_keywords:
        print(f"\n⚡ 뉴스+밈 AI 팩트체크 요약 중... ({len(needs_ai_keywords)}개)", flush=True)
        batch_summaries = get_batch_ai_summaries(needs_ai_keywords)

        for t_data in trend_data_list:
            if t_data['title'] in batch_summaries:
                t_data['summary'] = batch_summaries[t_data['title']]
                print(f"▶ [{t_data['title']}] 하이브리드 요약 및 위키 장착 완료!", flush=True)

    print("\n💾 수파베이스 저장 중...", flush=True)
    for t_data in trend_data_list:
        keyword = t_data['title']
        existing_data = supabase.table("google_trends").select("*").eq("title", keyword).execute()
        if existing_data.data:
            supabase.table("google_trends").update(t_data).eq("title", keyword).execute()
        else:
            supabase.table("google_trends").insert(t_data).execute()

    print("\n🎉 모든 업데이트가 단숨에 완료되었습니다!", flush=True)

if __name__ == "__main__":
    process_trends()