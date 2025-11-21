"""
Mass Spectrometry 論文研究システム（全体傾向要約機能追加版）
- 個別論文要約 → 全体傾向分析に変更
- Semantic Scholar Rate limit対策
- Gemini API最新モデル対応
"""
import streamlit as st
import sys
import os
from datetime import datetime, timedelta
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import matplotlib
import pandas as pd
from collections import Counter
import time
import requests
from typing import List, Dict, Optional
from xml.etree import ElementTree as ET
import re
from itertools import combinations
import networkx as nx
import json

# 日本語フォント設定（文字化け対策）
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

# ページ設定
st.set_page_config(
    page_title="Mass Spectrometry 論文研究システム",
    page_icon="📚",
    layout="wide"
)

# セッションステート初期化
if 'papers' not in st.session_state:
    st.session_state.papers = []
if 'gemini_api_key' not in st.session_state:
    st.session_state.gemini_api_key = ''


# ==================== PubMed Crawler ====================
class PubMedCrawler:
    """PubMed APIから論文情報を取得"""

    def __init__(self, email: str = "user@example.com"):
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.email = email

    def search_papers(self, keyword: str, max_results: int = 20, year_from: Optional[int] = None) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}esearch.fcgi"
            search_term = keyword
            if year_from:
                search_term = f"{keyword} AND {year_from}[PDAT]:{datetime.now().year}[PDAT]"

            search_params = {
                'db': 'pubmed',
                'term': search_term,
                'retmax': max_results,
                'retmode': 'json',
                'email': self.email
            }

            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()
            id_list = search_data.get('esearchresult', {}).get('idlist', [])

            if not id_list:
                return papers

            fetch_url = f"{self.base_url}efetch.fcgi"
            batch_size = 20
            for i in range(0, len(id_list), batch_size):
                batch_ids = id_list[i:i + batch_size]
                ids_str = ','.join(batch_ids)

                fetch_params = {'db': 'pubmed', 'id': ids_str, 'retmode': 'xml', 'email': self.email}
                fetch_response = requests.get(fetch_url, params=fetch_params, timeout=10)
                fetch_response.raise_for_status()
                root = ET.fromstring(fetch_response.content)

                for article in root.findall('.//PubmedArticle'):
                    try:
                        paper_info = self._extract_paper_info(article, keyword)
                        papers.append(paper_info)
                    except:
                        continue
                time.sleep(0.5)

            return papers

        except Exception as e:
            st.error(f"PubMed API エラー: {e}")
            return papers

    def _extract_paper_info(self, article_xml, keyword: str) -> Dict:
        article = article_xml.find('.//Article')
        title = article.findtext('.//ArticleTitle', 'N/A')

        authors = []
        for author in article.findall('.//Author'):
            lastname = author.findtext('LastName', '')
            forename = author.findtext('ForeName', '')
            if lastname:
                authors.append(f"{forename} {lastname}".strip())

        pub_date = article.find('.//PubDate')
        year = 'N/A'
        if pub_date is not None:
            year = pub_date.findtext('Year', 'N/A')

        abstract_texts = article.findall('.//AbstractText')
        abstract = ' '.join([a.text for a in abstract_texts if a.text]) if abstract_texts else 'N/A'

        venue = article.findtext('.//Journal/Title', 'N/A')
        pmid = article_xml.findtext('.//PMID', 'N/A')
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else 'N/A'

        return {
            'title': title, 'authors': authors, 'year': year, 'abstract': abstract,
            'venue': venue, 'url': url, 'pmid': pmid, 'citations': 0,
            'crawled_at': datetime.now().isoformat(), 'keyword': keyword, 'source': 'PubMed'
        }

    def get_recent_papers(self, keyword: str, days: int = 7, max_results: int = 20) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}esearch.fcgi"
            search_params = {
                'db': 'pubmed', 'term': keyword, 'retmax': max_results,
                'retmode': 'json', 'email': self.email, 'sort': 'date', 'reldate': days
            }

            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()
            id_list = search_data.get('esearchresult', {}).get('idlist', [])

            if not id_list:
                return papers

            fetch_url = f"{self.base_url}efetch.fcgi"
            ids_str = ','.join(id_list)
            fetch_params = {'db': 'pubmed', 'id': ids_str, 'retmode': 'xml', 'email': self.email}
            fetch_response = requests.get(fetch_url, params=fetch_params, timeout=10)
            fetch_response.raise_for_status()
            root = ET.fromstring(fetch_response.content)

            for article in root.findall('.//PubmedArticle'):
                try:
                    paper_info = self._extract_paper_info(article, keyword)
                    papers.append(paper_info)
                except:
                    continue

            return papers

        except Exception as e:
            st.error(f"検索エラー: {e}")
            return papers


# ==================== Semantic Scholar Crawler ====================
class SemanticScholarCrawler:
    """Semantic Scholar APIから論文情報を取得（Rate limit対策版）"""

    def __init__(self):
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.headers = {'User-Agent': 'Mozilla/5.0'}

    def search_papers(self, keyword: str, max_results: int = 20, year_from: Optional[int] = None) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}/paper/search"
            limit_per_request = min(max_results, 100)  # Semantic Scholarは100件まで対応
            params = {
                'query': keyword, 'limit': limit_per_request,
                'fields': 'title,authors,year,abstract,venue,citationCount,externalIds,url'
            }

            if year_from:
                params['year'] = f"{year_from}-"

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    time.sleep(1)
                    response = requests.get(search_url, params=params, headers=self.headers, timeout=15)
                    if response.status_code == 429:
                        wait_time = 5 * (attempt + 1)
                        st.warning(f"Rate limit検出。{wait_time}秒待機中...")
                        time.sleep(wait_time)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    break
                except requests.exceptions.HTTPError as e:
                    if attempt == max_retries - 1:
                        raise

            for paper_data in data.get('data', []):
                try:
                    authors = [author['name'] for author in paper_data.get('authors', [])]
                    year = paper_data.get('year', 'N/A')
                    external_ids = paper_data.get('externalIds', {})
                    paper_id = paper_data.get('paperId', '')
                    url = f"https://www.semanticscholar.org/paper/{paper_id}"
                    if external_ids.get('DOI'):
                        url = f"https://doi.org/{external_ids['DOI']}"

                    paper_info = {
                        'title': paper_data.get('title', 'N/A'), 'authors': authors,
                        'year': str(year) if year else 'N/A',
                        'abstract': paper_data.get('abstract') or 'N/A',
                        'venue': paper_data.get('venue') or 'N/A', 'url': url,
                        'citations': paper_data.get('citationCount', 0),
                        'crawled_at': datetime.now().isoformat(),
                        'keyword': keyword, 'source': 'Semantic Scholar'
                    }

                    papers.append(paper_info)

                except:
                    continue

            return papers

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                st.error("Semantic Scholar API Rate limitに達しました。数分後に再試行してください。")
                st.info("💡 代わりにPubMedをお試しください。")
            else:
                st.error(f"Semantic Scholar API エラー: {e}")
            return papers
        except Exception as e:
            st.error(f"検索エラー: {e}")
            return papers

    def get_recent_papers(self, keyword: str, days: int = 7, max_results: int = 20) -> List[Dict]:
        current_year = datetime.now().year
        return self.search_papers(keyword, max_results, year_from=current_year)


# ==================== Google Scholar Crawler ====================
class ScholarCrawler:
    """Google Scholarから論文情報を取得"""

    def __init__(self):
        self.results = []
        try:
            from scholarly import scholarly, ProxyGenerator
            self.scholarly = scholarly
            try:
                pg = ProxyGenerator()
                pg.FreeProxies()
                scholarly.use_proxy(pg)
            except:
                pass
        except ImportError:
            st.warning("scholarly ライブラリがインストールされていません")
            self.scholarly = None

    def search_papers(self, keyword: str, max_results: int = 20, year_from: Optional[int] = None) -> List[Dict]:
        if not self.scholarly:
            st.error("Google Scholar機能は利用できません")
            return []

        papers = []
        try:
            search_query = keyword
            if year_from:
                search_query = f"{keyword} after:{year_from}"

            search_results = self.scholarly.search_pubs(search_query)
            count = 0
            for result in search_results:
                if count >= max_results:
                    break

                try:
                    paper_info = {
                        'title': result.get('bib', {}).get('title', 'N/A'),
                        'authors': result.get('bib', {}).get('author', ['N/A']),
                        'year': result.get('bib', {}).get('pub_year', 'N/A'),
                        'abstract': result.get('bib', {}).get('abstract', 'N/A'),
                        'venue': result.get('bib', {}).get('venue', 'N/A'),
                        'url': result.get('pub_url', result.get('eprint_url', 'N/A')),
                        'citations': result.get('num_citations', 0),
                        'crawled_at': datetime.now().isoformat(),
                        'keyword': keyword, 'source': 'Google Scholar'
                    }

                    papers.append(paper_info)
                    count += 1
                    time.sleep(2)

                except:
                    continue

            return papers

        except Exception as e:
            st.error(f"Google Scholar エラー: {e}")
            st.info("💡 Google Scholarがブロックされました。Semantic ScholarまたはPubMedをお試しください。")
            return papers

    def get_recent_papers(self, keyword: str, days: int = 7, max_results: int = 20) -> List[Dict]:
        from_date = datetime.now() - timedelta(days=days)
        year_from = from_date.year
        return self.search_papers(keyword, max_results, year_from)


# ==================== テキスト解析 ====================
def extract_keywords(text: str, min_length: int = 4, top_n: int = 50) -> List[str]:
    """テキストからキーワードを抽出"""
    words = re.findall(r'\b[a-zA-Z]{' + str(min_length) + r',}\b', text.lower())
    stop_words = {
        'this', 'that', 'with', 'from', 'were', 'been', 'have', 'has', 'had',
        'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can',
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
        'was', 'said', 'them', 'than', 'find', 'also', 'made',
        'when', 'what', 'which', 'their', 'these', 'those', 'such', 'into',
        'through', 'during', 'before', 'after', 'about', 'between', 'under'
    }
    filtered_words = [w for w in words if w not in stop_words]
    word_counts = Counter(filtered_words)
    return [word for word, _ in word_counts.most_common(top_n)]


def build_cooccurrence_network(papers: List[Dict], top_keywords: int = 30, window_size: int = 10):
    """共起ネットワークを構築"""
    all_text = " ".join([f"{p['title']} {p['abstract']}" for p in papers if p['abstract'] != 'N/A'])
    keywords = extract_keywords(all_text, min_length=5, top_n=top_keywords)
    cooccurrence = Counter()

    for paper in papers:
        text = f"{paper['title']} {paper['abstract']}"
        words = re.findall(r'\b[a-zA-Z]{5,}\b', text.lower())
        for i, word1 in enumerate(words):
            if word1 not in keywords:
                continue
            for j in range(i + 1, min(i + window_size, len(words))):
                word2 = words[j]
                if word2 in keywords and word1 != word2:
                    pair = tuple(sorted([word1, word2]))
                    cooccurrence[pair] += 1
    return keywords, cooccurrence


# ==================== Gemini AI要約 ====================
def summarize_papers_with_gemini(papers: List[Dict], api_key: str, search_keyword: str) -> str:
    """Gemini APIを使って論文全体のトレンドと考察を生成"""
    try:
        import google.generativeai as genai

        # API設定
        genai.configure(api_key=api_key)
        # gemini-1.5-flashは安定版で無料枠が大きい
        model = genai.GenerativeModel('gemini-1.5-flash')

        # プロンプト作成
        papers_text = ""
        for i, paper in enumerate(papers[:20], 1):  # 最大20件まで
            abstract = paper.get('abstract', 'N/A')
            if abstract == 'N/A':
                abstract = "Abstract not available"
            papers_text += f"\n[Paper {i}]\nTitle: {paper['title']}\nYear: {paper['year']}\nAbstract: {abstract[:500]}...\n"

        prompt = f"""
あなたは研究トレンド分析の専門家です。以下の論文データを分析し、「{search_keyword}」に関する研究トレンドと考察を日本語で提供してください。

【論文データ】
{papers_text}

【分析内容】
1. **研究トレンドの概要**: この分野で現在注目されているテーマやアプローチ
2. **時系列的な変化**: 年代による研究の変遷や新しい動向
3. **主要な研究方向性**: どのような研究課題や応用分野が主流か
4. **今後の展望**: この分野の今後の発展可能性や注目すべきポイント

【出力形式】
- 各セクションを見出し付きで構造化
- 具体的な論文タイトルを引用しながら説明
- 専門的かつ分かりやすい表現で記述
- 合計800-1200文字程度
"""

        # API呼び出し
        response = model.generate_content(prompt)
        return response.text

    except ImportError:
        return "❌ エラー: google-generativeai ライブラリがインストールされていません。\n\n`pip install google-generativeai` を実行してください。"
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__

        # より詳細なエラー情報を表示
        full_error = f"エラータイプ: {error_type}\nエラー内容: {error_msg}"

        if "API_KEY_INVALID" in error_msg or "invalid" in error_msg.lower() and "key" in error_msg.lower():
            return f"❌ エラー: APIキーが無効です。正しいGemini APIキーを入力してください。\n\n{full_error}"
        elif "quota" in error_msg.lower() or "RESOURCE_EXHAUSTED" in error_msg:
            return f"❌ エラー: API利用制限に達しました。しばらく待ってから再試行してください。\n\n{full_error}"
        elif "404" in error_msg or "not found" in error_msg.lower() or "NOT_FOUND" in error_msg:
            return f"❌ エラー: モデルが見つかりません。\n\n現在使用中: gemini-1.5-flash\n代替モデル: gemini-1.5-pro, gemini-1.5-flash-8b\n\n{full_error}"
        elif "PERMISSION_DENIED" in error_msg or "permission" in error_msg.lower():
            return f"❌ エラー: APIキーの権限が不足しています。新しいAPIキーを作成してください。\n\n{full_error}"
        elif "blocked" in error_msg.lower() or "SAFETY" in error_msg:
            return f"❌ エラー: 安全性フィルターによりブロックされました。\n\n{full_error}"
        else:
            return f"❌ エラーが発生しました\n\n{full_error}\n\n💡 問題が解決しない場合は、APIキーを再確認するか、別のモデル（gemini-1.5-pro）をお試しください。"


# ==================== メインアプリケーション ====================
def main():
    st.title("📚 Mass Spectrometry 論文研究システム")
    st.markdown("高度な論文分析・トレンド解析・AI要約システム")
    st.markdown("---")

    # サイドバー
    with st.sidebar:
        st.header("⚙️ 設定")

        st.markdown("### 🤖 Gemini API設定")
        api_key_input = st.text_input(
            "Gemini APIキー",
            type="password",
            value=st.session_state.gemini_api_key,
            placeholder="AIキーを入力（AI要約機能用）"
        )
        if api_key_input:
            st.session_state.gemini_api_key = api_key_input

        st.markdown("[APIキー取得方法](https://aistudio.google.com/app/apikey)")
        st.markdown("---")

        st.markdown("### 📊 データソース比較")
        st.markdown("""
        **PubMed**
        - 医学・生命科学特化
        - 公式API・安定
        - 引用数なし

        **Semantic Scholar** ⭐
        - 全分野対応
        - 引用数あり
        - 無料・安定

        **Google Scholar**
        - 最大のDB
        - ブロックされやすい
        """)

    # タブ
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📚 論文検索", "📈 研究トレンド", "📊 統計分析", "🤖 AI要約",
        "☁️ ワードクラウド", "🕸️ 共起ネットワーク", "💾 保存データ"
    ])

    # タブ1: 論文検索
    with tab1:
        st.header("論文検索")

        data_source = st.radio(
            "データソース",
            ["PubMed（医学・生命科学）", "Semantic Scholar（全分野・引用数あり）", "Google Scholar（ブロック注意）"]
        )

        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input("検索キーワード", placeholder="例: mass spectrometry proteomics")
        with col2:
            max_results = st.number_input("取得件数", min_value=1, max_value=100, value=10)

        year_filter = st.checkbox("年で絞り込み")
        year_from = None
        if year_filter:
            year_from = st.slider("検索開始年", 2000, datetime.now().year, 2020)

        if st.button("🔍 論文を検索", type="primary"):
            if query:
                with st.spinner(f"{data_source}から論文を検索中..."):
                    try:
                        if "PubMed" in data_source:
                            crawler = PubMedCrawler()
                        elif "Semantic Scholar" in data_source:
                            crawler = SemanticScholarCrawler()
                        else:
                            crawler = ScholarCrawler()

                        papers = crawler.search_papers(query, max_results, year_from)

                        if papers:
                            st.session_state.papers = papers
                            st.session_state.search_keyword = query  # 検索キーワードを保存
                            st.success(f"✅ {len(papers)}件の論文を取得しました")
                            st.info("💡 データは「💾 保存データ」タブでいつでも確認・ダウンロードできます")
                        else:
                            st.warning("論文が見つかりませんでした")

                    except Exception as e:
                        st.error(f"エラー: {e}")

        # 検索結果の表示（検索ボタンの外に配置）
        if st.session_state.papers:
            st.markdown("---")
            st.markdown(f"### 📄 検索結果（全{len(st.session_state.papers)}件）")

            # ソートと表示件数の選択
            col1, col2 = st.columns([1, 1])

            with col1:
                sort_option = st.selectbox(
                    "並び替え",
                    options=[
                        "関連性順（デフォルト）",
                        "新しい順（年降順）",
                        "古い順（年昇順）",
                        "引用数順（多い順）",
                        "著者名順（A-Z）",
                        "ジャーナル名順（A-Z）"
                    ],
                    index=0,
                    key="sort_option_select"
                )

            with col2:
                display_options = [10, 20, 50, 100]
                if len(st.session_state.papers) > 100:
                    display_options.append("全件表示")
                else:
                    display_options.append(f"全{len(st.session_state.papers)}件")

                display_count = st.selectbox(
                    "表示件数",
                    options=display_options,
                    index=0,
                    key="display_count_select"
                )

            # ソート処理
            sorted_papers = st.session_state.papers.copy()

            if sort_option == "新しい順（年降順）":
                sorted_papers = sorted(
                    sorted_papers,
                    key=lambda x: int(x['year']) if x['year'] != 'N/A' and str(x['year']).isdigit() else 0,
                    reverse=True
                )
            elif sort_option == "古い順（年昇順）":
                sorted_papers = sorted(
                    sorted_papers,
                    key=lambda x: int(x['year']) if x['year'] != 'N/A' and str(x['year']).isdigit() else 9999,
                    reverse=False
                )
            elif sort_option == "引用数順（多い順）":
                sorted_papers = sorted(
                    sorted_papers,
                    key=lambda x: x.get('citations', 0),
                    reverse=True
                )
            elif sort_option == "著者名順（A-Z）":
                sorted_papers = sorted(
                    sorted_papers,
                    key=lambda x: (x['authors'][0] if isinstance(x['authors'], list) and len(x['authors']) > 0 else x['authors']) if x['authors'] else 'zzz'
                )
            elif sort_option == "ジャーナル名順（A-Z）":
                sorted_papers = sorted(
                    sorted_papers,
                    key=lambda x: x.get('venue', 'zzz') if x.get('venue') != 'N/A' else 'zzz'
                )
            # 関連性順（デフォルト）の場合は何もしない

            if isinstance(display_count, str):  # "全件表示" or "全X件"
                display_count = len(sorted_papers)

            papers_to_display = sorted_papers[:display_count]

            for i, paper in enumerate(papers_to_display, 1):
                with st.expander(f"📄 {i}. {paper['title'][:80]}..."):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        authors_str = ', '.join(paper['authors'][:3]) if isinstance(paper['authors'], list) else paper['authors']
                        st.markdown(f"**著者**: {authors_str}")
                        st.markdown(f"**年**: {paper['year']}")
                        st.markdown(f"**掲載**: {paper.get('venue', 'N/A')}")
                        st.markdown(f"**URL**: [{paper['url']}]({paper['url']})")
                    with col2:
                        if paper.get('citations', 0) > 0:
                            st.metric("引用数", paper['citations'])

                    if paper.get('abstract') and paper['abstract'] != 'N/A':
                        st.markdown(f"**要旨**: {paper['abstract'][:400]}...")

    # タブ2: 研究トレンド
    with tab2:
        st.header("📈 研究トレンド分析")

        if st.session_state.papers:
            st.subheader("Year-wise Publication Trend")
            years = [p['year'] for p in st.session_state.papers if p['year'] != 'N/A' and str(p['year']).isdigit()]

            if years:
                year_counts = Counter(years)
                year_df = pd.DataFrame(list(year_counts.items()), columns=['Year', 'Count']).sort_values('Year')

                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(year_df['Year'], year_df['Count'], marker='o', linewidth=2, markersize=8)
                ax.set_xlabel('Year', fontsize=12)
                ax.set_ylabel('Number of Papers', fontsize=12)
                ax.set_title('Publication Trend by Year', fontsize=14, fontweight='bold')
                ax.grid(True, alpha=0.3)
                st.pyplot(fig)

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Papers", len(years))
                with col2:
                    peak_year = year_counts.most_common(1)[0][0]
                    st.metric("Peak Year", peak_year)
                with col3:
                    avg_per_year = len(years) / len(year_counts) if year_counts else 0
                    st.metric("Avg/Year", f"{avg_per_year:.1f}")
            else:
                st.warning("年データが不足しています")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ3: 統計的全体傾向分析
    with tab3:
        st.header("📊 統計分析")
        st.markdown("検索した論文全体の研究トレンドを統計的に分析します（APIキー不要）")

        if st.session_state.papers:
            if st.button("📊 統計分析を実行", type="primary"):
                papers_to_analyze = st.session_state.papers

                with st.spinner("分析中..."):
                    # 1. 基本統計
                    st.markdown("---")
                    st.markdown("### 📈 基本統計")
                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        st.metric("総論文数", len(papers_to_analyze))

                    with col2:
                        years = [p['year'] for p in papers_to_analyze if p['year'] != 'N/A' and str(p['year']).isdigit()]
                        if years:
                            year_range = f"{min(years)}-{max(years)}"
                            st.metric("対象年範囲", year_range)

                    with col3:
                        total_citations = sum([p.get('citations', 0) for p in papers_to_analyze])
                        st.metric("総引用数", total_citations)

                    with col4:
                        avg_citations = total_citations / len(papers_to_analyze) if papers_to_analyze else 0
                        st.metric("平均引用数", f"{avg_citations:.1f}")

                    # 2. 頻出キーワード分析
                    st.markdown("---")
                    st.markdown("### 🔑 頻出キーワード Top 20")
                    all_text = " ".join([f"{p['title']} {p['abstract']}" for p in papers_to_analyze if p['abstract'] != 'N/A'])
                    keywords = extract_keywords(all_text, min_length=5, top_n=20)

                    if keywords:
                        # キーワードの出現回数を計算
                        keyword_counts = Counter()
                        for paper in papers_to_analyze:
                            text = f"{paper['title']} {paper['abstract']}".lower()
                            for kw in keywords:
                                keyword_counts[kw] += text.count(kw)

                        # 棒グラフで表示
                        kw_df = pd.DataFrame(list(keyword_counts.most_common(20)), columns=['Keyword', 'Count'])
                        fig, ax = plt.subplots(figsize=(12, 6))
                        ax.barh(kw_df['Keyword'], kw_df['Count'], color='skyblue')
                        ax.set_xlabel('Frequency', fontsize=12)
                        ax.set_ylabel('Keywords', fontsize=12)
                        ax.set_title('Top 20 Keywords', fontsize=14, fontweight='bold')
                        ax.invert_yaxis()
                        st.pyplot(fig)

                    # 3. 年代別キーワード分析
                    st.markdown("---")
                    st.markdown("### 📅 年代別の主要キーワード")
                    if years:
                        year_keywords = {}
                        for year in sorted(set(years)):
                            year_papers = [p for p in papers_to_analyze if str(p['year']) == str(year)]
                            year_text = " ".join([f"{p['title']} {p['abstract']}" for p in year_papers if p['abstract'] != 'N/A'])
                            year_kws = extract_keywords(year_text, min_length=5, top_n=5)
                            year_keywords[year] = year_kws

                        for year in sorted(year_keywords.keys()):
                            st.markdown(f"**{year}年**: {', '.join(year_keywords[year][:5])}")

                    # 4. 主要著者分析
                    st.markdown("---")
                    st.markdown("### 👥 主要著者 Top 10")
                    all_authors = []
                    for paper in papers_to_analyze:
                        authors = paper['authors']
                        if isinstance(authors, list):
                            all_authors.extend(authors)
                        else:
                            all_authors.append(authors)

                    author_counts = Counter(all_authors)
                    top_authors = author_counts.most_common(10)

                    if top_authors:
                        author_df = pd.DataFrame(top_authors, columns=['Author', 'Papers'])
                        st.dataframe(author_df, use_container_width=True)

                    # 5. 掲載ジャーナル分析
                    st.markdown("---")
                    st.markdown("### 📚 主要掲載ジャーナル Top 10")
                    venues = [p['venue'] for p in papers_to_analyze if p.get('venue') and p['venue'] != 'N/A']
                    venue_counts = Counter(venues)
                    top_venues = venue_counts.most_common(10)

                    if top_venues:
                        venue_df = pd.DataFrame(top_venues, columns=['Journal', 'Papers'])
                        st.dataframe(venue_df, use_container_width=True)

                    # 6. 引用数分布
                    st.markdown("---")
                    st.markdown("### 📊 引用数分布")
                    citations = [p.get('citations', 0) for p in papers_to_analyze if p.get('citations', 0) > 0]

                    if citations:
                        fig, ax = plt.subplots(figsize=(12, 5))
                        ax.hist(citations, bins=20, color='lightcoral', edgecolor='black', alpha=0.7)
                        ax.set_xlabel('Citations', fontsize=12)
                        ax.set_ylabel('Number of Papers', fontsize=12)
                        ax.set_title('Citation Distribution', fontsize=14, fontweight='bold')
                        ax.grid(True, alpha=0.3)
                        st.pyplot(fig)

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("最多引用数", max(citations))
                        with col2:
                            st.metric("中央値", int(pd.Series(citations).median()))
                        with col3:
                            st.metric("平均値", f"{pd.Series(citations).mean():.1f}")

                    st.success("✅ 統計分析完了！")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ4: AI要約
    with tab4:
        st.header("🤖 AI要約（Gemini）")
        st.markdown("""
        ### 📖 AI要約とは？
        Google Gemini AIを使って、検索した論文の**タイトル**と**要旨（Abstract）**から、
        研究トレンドと考察を自動生成します。

        **分析内容:**
        - 研究トレンドの概要
        - 時系列的な変化
        - 主要な研究方向性
        - 今後の展望

        **注意:** Gemini APIキーが必要です（サイドバーで設定）
        """)
        st.markdown("---")

        if st.session_state.papers:
            if not st.session_state.gemini_api_key:
                st.warning("⚠️ Gemini APIキーが設定されていません。サイドバーで設定してください。")
            else:
                st.info(f"📊 現在 {len(st.session_state.papers)} 件の論文データがあります（最大20件まで分析）")

                # 検索キーワードの取得（session_stateに保存する）
                if 'search_keyword' not in st.session_state:
                    st.session_state.search_keyword = st.session_state.papers[0].get('keyword', 'Unknown') if st.session_state.papers else 'Unknown'

                if st.button("🤖 AI要約を生成", type="primary"):
                    with st.spinner("Gemini AIが分析中...（30秒程度かかります）"):
                        summary = summarize_papers_with_gemini(
                            st.session_state.papers,
                            st.session_state.gemini_api_key,
                            st.session_state.search_keyword
                        )

                        st.markdown("---")
                        st.markdown("### 📝 AI生成トレンド分析")
                        st.markdown(summary)
                        st.success("✅ AI要約完了！")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ5: ワードクラウド
    with tab5:
        st.header("☁️ ワードクラウド生成")
        st.markdown("""
        ### 📖 ワードクラウドとは？
        検索した論文の**タイトル**と**要旨（Abstract）**から頻出単語を抽出し、
        出現頻度に応じて文字サイズを変えて視覚化します。

        **活用方法:**
        - 研究分野で頻繁に使われる専門用語を一目で把握
        - 研究トレンドの中心的なキーワードを発見
        - プレゼンテーション資料やレポートの作成に活用
        """)
        st.markdown("---")

        if st.session_state.papers:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.info(f"現在 {len(st.session_state.papers)} 件の論文データがあります")
            with col2:
                max_words = st.slider("最大単語数", 30, 200, 100)

            if st.button("☁️ ワードクラウドを生成"):
                with st.spinner("生成中..."):
                    text = " ".join([f"{p['title']} {p['abstract']}" for p in st.session_state.papers if p['abstract'] != 'N/A'])
                    if text:
                        wordcloud = WordCloud(width=1200, height=600, background_color='white', colormap='viridis', max_words=max_words).generate(text)
                        fig, ax = plt.subplots(figsize=(15, 7))
                        ax.imshow(wordcloud, interpolation='bilinear')
                        ax.axis('off')
                        st.pyplot(fig)
                        st.success("✅ ワードクラウド生成完了")
                    else:
                        st.warning("テキストデータが不足しています")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ6: 共起ネットワーク
    with tab6:
        st.header("🕸️ 共起ネットワーク解析")
        st.markdown("""
        ### 📖 共起ネットワークとは？
        検索した論文の**タイトル**と**要旨（Abstract）**から、
        **同じ文脈で一緒に出現する単語（共起関係）**をネットワーク図として可視化します。

        **読み方:**
        - **ノード（円）**: 頻出キーワード。円が大きいほど他の単語との関連性が高い
        - **エッジ（線）**: 単語間の共起関係。線が太いほど一緒に出現する回数が多い
        - **クラスター**: 密に繋がっている単語群は、関連する研究テーマを示す

        **活用方法:**
        - 研究分野内の概念同士の関連性を把握
        - 新しい研究アイデアの発見（意外な単語の組み合わせ）
        - 研究領域のマップ作成
        - 文献レビューの構造化

        **パラメータ説明:**
        - **表示キーワード数**: ネットワークに含めるキーワードの数
        - **共起ウィンドウ**: 何単語離れていても「共起」とみなすか（大きいほど広範囲）
        - **最小共起回数**: 何回以上一緒に出現した単語を線で結ぶか（大きいほど強い関係のみ表示）
        """)
        st.markdown("---")

        if st.session_state.papers:
            col1, col2, col3 = st.columns(3)
            with col1:
                top_keywords = st.slider("表示キーワード数", 10, 50, 30)
            with col2:
                window_size = st.slider("共起ウィンドウ", 5, 20, 10)
            with col3:
                min_cooccurrence = st.slider("最小共起回数", 1, 10, 2)

            if st.button("🕸️ 共起ネットワークを生成"):
                with st.spinner("解析中..."):
                    keywords, cooccurrence = build_cooccurrence_network(st.session_state.papers, top_keywords, window_size)
                    G = nx.Graph()
                    for (word1, word2), count in cooccurrence.items():
                        if count >= min_cooccurrence:
                            G.add_edge(word1, word2, weight=count)

                    if len(G.nodes()) > 0:
                        pos = nx.spring_layout(G, k=0.5, iterations=50)
                        fig, ax = plt.subplots(figsize=(16, 12))
                        node_sizes = [G.degree(node) * 300 for node in G.nodes()]
                        nx.draw_networkx_nodes(G, pos, node_size=node_sizes, node_color='lightblue', alpha=0.7, ax=ax)
                        edges = G.edges()
                        weights = [G[u][v]['weight'] for u, v in edges]
                        max_weight = max(weights) if weights else 1
                        nx.draw_networkx_edges(G, pos, width=[w / max_weight * 5 for w in weights], alpha=0.3, ax=ax)
                        nx.draw_networkx_labels(G, pos, font_size=10, font_weight='bold', ax=ax)
                        ax.axis('off')
                        ax.set_title(f"Co-occurrence Network (Nodes: {len(G.nodes())}, Edges: {len(G.edges())})", fontsize=16)
                        st.pyplot(fig)

                        st.subheader("Network Statistics")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Nodes", len(G.nodes()))
                        with col2:
                            st.metric("Edges", len(G.edges()))
                        with col3:
                            if len(G.nodes()) > 0:
                                avg_degree = sum(dict(G.degree()).values()) / len(G.nodes())
                                st.metric("Avg Degree", f"{avg_degree:.2f}")
                        st.success("✅ 共起ネットワーク生成完了")
                    else:
                        st.warning("共起関係が見つかりませんでした")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ7: 保存データ
    with tab7:
        st.header("💾 保存されたデータ")
        if st.session_state.papers:
            st.subheader("🏆 引用数ランキング（Top 10）")
            papers_with_citations = [p for p in st.session_state.papers if p.get('citations', 0) > 0]
            if papers_with_citations:
                sorted_papers = sorted(papers_with_citations, key=lambda x: x.get('citations', 0), reverse=True)[:10]
                for i, paper in enumerate(sorted_papers, 1):
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        st.markdown(f"**{i}. {paper['title'][:70]}...**")
                        authors_str = ', '.join(paper['authors'][:2]) if isinstance(paper['authors'], list) else paper['authors']
                        st.caption(f"{authors_str} ({paper['year']})")
                    with col2:
                        st.metric("Citations", paper['citations'])
            else:
                st.info("引用数データがありません")

            st.markdown("---")
            st.subheader("📚 取得済み論文")
            df_data = []
            for p in st.session_state.papers:
                authors_list = p['authors']
                if isinstance(authors_list, list):
                    authors_str = ', '.join(authors_list[:2])
                    if len(authors_list) > 2:
                        authors_str += '...'
                else:
                    authors_str = authors_list[:50]
                df_data.append({
                    'Title': p['title'][:60] + '...' if len(p['title']) > 60 else p['title'],
                    'Authors': authors_str, 'Year': p['year'],
                    'Source': p.get('source', 'N/A'), 'Citations': p.get('citations', 0)
                })
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True)

            csv = pd.DataFrame(st.session_state.papers).to_csv(index=False, encoding='utf-8-sig')
            st.download_button(label="📥 CSV Download", data=csv, file_name=f"papers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")

            st.subheader("📊 Statistics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Papers", len(st.session_state.papers))
            with col2:
                years = [p['year'] for p in st.session_state.papers if p['year'] != 'N/A']
                if years:
                    year_counts = Counter(years)
                    most_common_year = year_counts.most_common(1)[0][0]
                    st.metric("Most Common Year", most_common_year)
            with col3:
                if years:
                    st.metric("Latest Year", max(years))
            with col4:
                total_citations = sum([p.get('citations', 0) for p in st.session_state.papers])
                st.metric("Total Citations", total_citations)
        else:
            st.info("まだデータがありません")


if __name__ == "__main__":
    main()
