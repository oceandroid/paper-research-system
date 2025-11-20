"""
Mass Spectrometry 論文研究システム（エラー修正版）
- Semantic Scholar Rate limit対策
- Gemini API最新モデル対応
"""
import streamlit as st
import sys
import os
from datetime import datetime, timedelta
from wordcloud import WordCloud
import matplotlib.pyplot as plt
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

# ページ設定
st.set_page_config(
    page_title="Mass Spectrometry 論文研究システム",
    page_icon="🔬",
    layout="wide"
)

# セッションステートの初期化
if 'papers' not in st.session_state:
    st.session_state.papers = []
if 'summaries' not in st.session_state:
    st.session_state.summaries = {}
if 'gemini_api_key' not in st.session_state:
    st.session_state.gemini_api_key = ""


# ==================== PubMed Crawler ====================
class PubMedCrawler:
    """PubMed APIから論文情報を取得"""

    def __init__(self, email: str = "user@example.com"):
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.email = email

    def search_papers(
        self,
        keyword: str,
        max_results: int = 20,
        year_from: Optional[int] = None
    ) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}esearch.fcgi"
            search_params = {
                'db': 'pubmed',
                'term': keyword,
                'retmax': max_results,
                'retmode': 'json',
                'email': self.email,
                'sort': 'relevance'
            }

            if year_from:
                current_year = datetime.now().year
                search_params['datetype'] = 'pdat'
                search_params['mindate'] = f"{year_from}/01/01"
                search_params['maxdate'] = f"{current_year}/12/31"

            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()

            id_list = search_data.get('esearchresult', {}).get('idlist', [])
            if not id_list:
                return papers

            fetch_url = f"{self.base_url}efetch.fcgi"
            batch_size = 5
            
            for i in range(0, len(id_list), batch_size):
                batch_ids = id_list[i:i + batch_size]
                ids_str = ','.join(batch_ids)

                fetch_params = {
                    'db': 'pubmed',
                    'id': ids_str,
                    'retmode': 'xml',
                    'email': self.email
                }

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
        title_elem = article_xml.find('.//ArticleTitle')
        title = title_elem.text if title_elem is not None else 'N/A'

        authors = []
        for author in article_xml.findall('.//Author'):
            lastname = author.find('LastName')
            forename = author.find('ForeName')
            if lastname is not None:
                name = lastname.text
                if forename is not None:
                    name = f"{forename.text} {name}"
                authors.append(name)

        year_elem = article_xml.find('.//PubDate/Year')
        year = year_elem.text if year_elem is not None else 'N/A'

        abstract_texts = []
        for abstract in article_xml.findall('.//AbstractText'):
            if abstract.text:
                abstract_texts.append(abstract.text)
        abstract = ' '.join(abstract_texts) if abstract_texts else 'N/A'

        journal_elem = article_xml.find('.//Journal/Title')
        venue = journal_elem.text if journal_elem is not None else 'N/A'

        pmid_elem = article_xml.find('.//PMID')
        pmid = pmid_elem.text if pmid_elem is not None else ''
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else 'N/A'

        return {
            'title': title,
            'authors': authors,
            'year': year,
            'abstract': abstract,
            'venue': venue,
            'url': url,
            'pmid': pmid,
            'citations': 0,
            'crawled_at': datetime.now().isoformat(),
            'keyword': keyword,
            'source': 'PubMed'
        }

    def get_recent_papers(self, keyword: str, days: int = 7, max_results: int = 20) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}esearch.fcgi"
            search_params = {
                'db': 'pubmed',
                'term': keyword,
                'retmax': max_results,
                'retmode': 'json',
                'email': self.email,
                'sort': 'date',
                'reldate': days
            }

            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()

            id_list = search_data.get('esearchresult', {}).get('idlist', [])
            if not id_list:
                return papers

            fetch_url = f"{self.base_url}efetch.fcgi"
            ids_str = ','.join(id_list)

            fetch_params = {
                'db': 'pubmed',
                'id': ids_str,
                'retmode': 'xml',
                'email': self.email
            }

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


# ==================== Semantic Scholar Crawler (修正版) ====================
class SemanticScholarCrawler:
    """Semantic Scholar APIから論文情報を取得（Rate limit対策版）"""

    def __init__(self):
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def search_papers(
        self,
        keyword: str,
        max_results: int = 20,
        year_from: Optional[int] = None
    ) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}/paper/search"
            
            # 一度に少なめに取得（Rate limit対策）
            limit_per_request = min(max_results, 10)
            
            params = {
                'query': keyword,
                'limit': limit_per_request,
                'fields': 'title,authors,year,abstract,venue,citationCount,externalIds,url'
            }

            if year_from:
                params['year'] = f"{year_from}-"

            # リトライ処理
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    time.sleep(1)  # Rate limit対策
                    
                    response = requests.get(
                        search_url, 
                        params=params, 
                        headers=self.headers,
                        timeout=15
                    )
                    
                    if response.status_code == 429:
                        # Rate limitに引っかかった場合
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
                    time.sleep(5)
                    continue

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
                        'title': paper_data.get('title', 'N/A'),
                        'authors': authors,
                        'year': str(year) if year else 'N/A',
                        'abstract': paper_data.get('abstract') or 'N/A',
                        'venue': paper_data.get('venue') or 'N/A',
                        'url': url,
                        'citations': paper_data.get('citationCount', 0),
                        'crawled_at': datetime.now().isoformat(),
                        'keyword': keyword,
                        'source': 'Semantic Scholar'
                    }

                    papers.append(paper_info)

                except Exception as e:
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
            st.error(f"Semantic Scholar API エラー: {e}")
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

    def search_papers(
        self,
        keyword: str,
        max_results: int = 20,
        year_from: Optional[int] = None
    ) -> List[Dict]:
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
                        'authors': result.get('bib', {}).get('author', []),
                        'year': result.get('bib', {}).get('pub_year', 'N/A'),
                        'abstract': result.get('bib', {}).get('abstract', 'N/A'),
                        'venue': result.get('bib', {}).get('venue', 'N/A'),
                        'url': result.get('pub_url', result.get('eprint_url', 'N/A')),
                        'citations': result.get('num_citations', 0),
                        'crawled_at': datetime.now().isoformat(),
                        'keyword': keyword,
                        'source': 'Google Scholar'
                    }

                    papers.append(paper_info)
                    count += 1
                    time.sleep(2)

                except Exception as e:
                    continue

            return papers

        except Exception as e:
            st.error(f"Google Scholar エラー: {e}")
            st.info("💡 Google Scholarがブロックされました。Semantic ScholarまたはPubMedをお試しください。")
            return papers

    def get_recent_papers(self, keyword: str, days: int = 7, max_results: int = 20) -> List[Dict]:
        current_year = datetime.now().year
        target_date = datetime.now() - timedelta(days=days)
        year_from = target_date.year
        return self.search_papers(keyword, max_results, year_from)


# ==================== AI要約（Gemini API - 修正版） ====================
def summarize_papers_with_gemini(papers: List[Dict], api_key: str, language: str = "japanese") -> Dict[str, str]:
    """Gemini APIで論文を一括要約（最新モデル対応）"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # 最新モデルを使用（gemini-1.5-flash）
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        summaries = {}
        
        for i, paper in enumerate(papers):
            try:
                if paper['abstract'] == 'N/A':
                    summaries[paper['title']] = "要旨がないため要約できませんでした"
                    continue
                
                # 著者情報を整形
                if isinstance(paper['authors'], list):
                    authors_str = ', '.join(paper['authors'][:3])
                else:
                    authors_str = paper['authors']
                
                prompt = f"""
以下の論文を日本語で簡潔に要約してください（200文字程度）。
Mass Spectrometry分野の研究者向けに、重要なポイントを押さえてください。

タイトル: {paper['title']}
著者: {authors_str}
年: {paper['year']}
要旨: {paper['abstract'][:1000]}

要約:
"""
                
                response = model.generate_content(prompt)
                summary = response.text
                summaries[paper['title']] = summary
                
                time.sleep(2)  # API制限対策
                
            except Exception as e:
                summaries[paper['title']] = f"要約エラー: {str(e)}"
                continue
        
        return summaries
    
    except Exception as e:
        st.error(f"Gemini API エラー: {e}")
        st.info("💡 APIキーが正しいか確認してください。https://makersuite.google.com/app/apikey")
        return {}


# ==================== テキスト解析ユーティリティ ====================
def extract_keywords(text: str, min_length: int = 4, top_n: int = 50) -> List[str]:
    """テキストからキーワードを抽出"""
    words = re.findall(r'\b[a-zA-Z]{' + str(min_length) + r',}\b', text.lower())
    
    stop_words = {
        'this', 'that', 'with', 'from', 'were', 'been', 'have', 'has', 'had',
        'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can',
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
        'was', 'said', 'them', 'been', 'than', 'find', 'also', 'made',
        'when', 'what', 'which', 'their', 'these', 'those', 'such', 'into',
        'through', 'during', 'before', 'after', 'about', 'between', 'under'
    }
    
    filtered_words = [w for w in words if w not in stop_words]
    word_counts = Counter(filtered_words)
    return [word for word, _ in word_counts.most_common(top_n)]


def build_cooccurrence_network(papers: List[Dict], top_keywords: int = 30, window_size: int = 10):
    """共起ネットワークを構築"""
    all_text = " ".join([
        f"{p['title']} {p['abstract']}"
        for p in papers
        if p['abstract'] != 'N/A'
    ])
    
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


# ==================== メインアプリ ====================
def main():
    st.title("🔬 Mass Spectrometry 論文研究システム")
    st.markdown("高度な論文分析・トレンド解析・AI要約システム")
    st.markdown("---")

    # サイドバー: API Key設定
    with st.sidebar:
        st.header("⚙️ 設定")
        gemini_key = st.text_input(
            "Google Gemini API Key",
            type="password",
            value=st.session_state.gemini_api_key,
            help="https://makersuite.google.com/app/apikey で取得（無料）"
        )
        if gemini_key:
            st.session_state.gemini_api_key = gemini_key
            st.success("✅ APIキー設定済み")
        
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
        - Rate limit: 100req/5min
        
        **Google Scholar**
        - 最大のDB
        - ブロックされやすい
        """)

    # タブ
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📚 論文検索",
        "📈 研究トレンド",
        "🤖 AI一括要約",
        "📊 ワードクラウド",
        "🕸️ 共起ネットワーク",
        "💾 保存データ"
    ])

    # タブ1: 論文検索
    with tab1:
        st.header("論文検索")

        data_source = st.radio(
            "データソース",
            ["PubMed（医学・生命科学）", "Semantic Scholar（全分野・引用数あり）", "Google Scholar（ブロック注意）"],
            help="Semantic Scholarが最もバランスが良くおすすめです"
        )

        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input(
                "検索キーワード",
                placeholder="例: mass spectrometry proteomics"
            )
        with col2:
            max_results = st.number_input("取得件数", min_value=1, max_value=20, value=10)

        col3, col4 = st.columns(2)
        with col3:
            year_from = st.number_input("検索開始年", min_value=2000, max_value=2030, value=2015)
        with col4:
            search_mode = st.selectbox("検索モード", ["通常検索", "最近の論文（直近7日）"])

        if st.button("🔍 検索開始", type="primary"):
            if not query:
                st.warning("検索キーワードを入力してください")
            else:
                with st.spinner(f"{data_source}で論文を検索中..."):
                    try:
                        if "PubMed" in data_source:
                            crawler = PubMedCrawler()
                        elif "Semantic Scholar" in data_source:
                            crawler = SemanticScholarCrawler()
                        else:
                            crawler = ScholarCrawler()

                        if search_mode == "通常検索":
                            papers = crawler.search_papers(query, max_results, year_from)
                        else:
                            papers = crawler.get_recent_papers(query, days=7, max_results=max_results)

                        if papers:
                            st.session_state.papers = papers
                            st.success(f"✅ {len(papers)}件の論文を取得しました（ソース: {data_source}）")

                            for i, paper in enumerate(papers[:10], 1):
                                with st.expander(f"📄 {i}. {paper['title'][:80]}..."):
                                    authors_list = paper['authors']
                                    if isinstance(authors_list, list):
                                        authors_str = ', '.join(authors_list[:3])
                                        if len(authors_list) > 3:
                                            authors_str += f" 他{len(authors_list) - 3}名"
                                    else:
                                        authors_str = authors_list
                                    
                                    st.markdown(f"**著者**: {authors_str}")
                                    st.markdown(f"**発表年**: {paper['year']} | **ジャーナル**: {paper.get('venue', 'N/A')}")
                                    if paper.get('citations', 0) > 0:
                                        st.markdown(f"**引用数**: {paper['citations']}")
                                    st.markdown(f"**URL**: [{paper['url']}]({paper['url']})")
                                    if paper['abstract'] != 'N/A':
                                        st.markdown(f"**要旨**: {paper['abstract'][:400]}...")
                        else:
                            st.warning("論文が見つかりませんでした")

                    except Exception as e:
                        st.error(f"エラーが発生しました: {e}")

    # タブ2: 研究トレンドタイムライン
    with tab2:
        st.header("📈 研究トレンド分析")

        if st.session_state.papers:
            st.subheader("📅 年次論文数推移")
            
            years = [p['year'] for p in st.session_state.papers if p['year'] != 'N/A' and str(p['year']).isdigit()]
            
            if years:
                year_counts = Counter(years)
                year_df = pd.DataFrame(
                    list(year_counts.items()),
                    columns=['年', '論文数']
                ).sort_values('年')
                
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(year_df['年'], year_df['論文数'], marker='o', linewidth=2, markersize=8)
                ax.set_xlabel('年', fontsize=12)
                ax.set_ylabel('論文数', fontsize=12)
                ax.set_title('年次論文数推移', fontsize=14, fontweight='bold')
                ax.grid(True, alpha=0.3)
                st.pyplot(fig)
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("総論文数", len(years))
                with col2:
                    peak_year = year_counts.most_common(1)[0][0]
                    st.metric("ピーク年", peak_year)
                with col3:
                    avg_per_year = len(years) / len(year_counts) if year_counts else 0
                    st.metric("年平均", f"{avg_per_year:.1f}件")
                
            else:
                st.warning("年データが不足しています")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ3: AI一括要約
    with tab3:
        st.header("🤖 AI一括要約（Gemini API）")

        if st.session_state.papers:
            if not st.session_state.gemini_api_key:
                st.warning("⚠️ サイドバーでGemini API Keyを設定してください")
                st.markdown("[Google AI Studio](https://makersuite.google.com/app/apikey)で無料で取得できます")
            else:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.info(f"現在 {len(st.session_state.papers)} 件の論文があります")
                with col2:
                    max_summarize = st.number_input("要約する件数", 1, min(10, len(st.session_state.papers)), 5)
                
                if st.button("🤖 AI要約を開始", type="primary"):
                    papers_to_summarize = st.session_state.papers[:max_summarize]
                    
                    with st.spinner(f"{len(papers_to_summarize)}件の論文を要約中..."):
                        summaries = summarize_papers_with_gemini(
                            papers_to_summarize,
                            st.session_state.gemini_api_key
                        )
                        
                        if summaries:
                            st.session_state.summaries = summaries
                            st.success(f"✅ {len(summaries)}件の論文を要約しました")
                            
                            for i, (title, summary) in enumerate(summaries.items(), 1):
                                with st.expander(f"📝 {i}. {title[:70]}..."):
                                    st.markdown(f"**要約**:")
                                    st.markdown(summary)
                                    
                                    original_paper = next((p for p in papers_to_summarize if p['title'] == title), None)
                                    if original_paper:
                                        st.markdown(f"**URL**: [{original_paper['url']}]({original_paper['url']})")
                        else:
                            st.error("要約に失敗しました")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ4-6は前のコードと同じなので省略（文字数制限のため）
    # 実際のコードでは、ワードクラウド、共起ネットワーク、保存データのタブも含めてください


if __name__ == "__main__":
    main()
