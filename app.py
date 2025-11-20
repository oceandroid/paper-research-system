"""
Mass Spectrometry 論文研究システム（完全版・全エラー修正済み）
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
import networkx as nx
import json

# 日本語フォント設定（文字化け対策）
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

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
    def __init__(self, email: str = "user@example.com"):
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.email = email

    def search_papers(self, keyword: str, max_results: int = 20, year_from: Optional[int] = None) -> List[Dict]:
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
    def __init__(self):
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.headers = {'User-Agent': 'Mozilla/5.0'}

    def search_papers(self, keyword: str, max_results: int = 20, year_from: Optional[int] = None) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}/paper/search"
            limit_per_request = min(max_results, 10)
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
                        'authors': result.get('bib', {}).get('author', []),
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
            return papers

    def get_recent_papers(self, keyword: str, days: int = 7, max_results: int = 20) -> List[Dict]:
        current_year = datetime.now().year
        target_date = datetime.now() - timedelta(days=days)
        year_from = target_date.year
        return self.search_papers(keyword, max_results, year_from)


# ==================== AI要約（Gemini API） ====================
def summarize_papers_with_gemini(papers: List[Dict], api_key: str) -> Dict[str, str]:
    """Gemini APIで論文を一括要約"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # 利用可能なモデルを取得して最適なものを選択
        try:
            model = genai.GenerativeModel('gemini-1.5-pro-latest')
        except:
            try:
                model = genai.GenerativeModel('gemini-pro')
            except:
                st.error("利用可能なGeminiモデルが見つかりません")
                return {}
        
        summaries = {}
        
        for i, paper in enumerate(papers):
            try:
                if paper['abstract'] == 'N/A':
                    summaries[paper['title']] = "要旨がないため要約できませんでした"
                    continue
                
                if isinstance(paper['authors'], list):
                    authors_str = ', '.join(paper['authors'][:3])
                else:
                    authors_str = paper['authors']
                
                prompt = f"""以下の論文を日本語で簡潔に要約してください（200文字程度）。
Mass Spectrometry分野の研究者向けに、重要なポイントを押さえてください。

タイトル: {paper['title']}
著者: {authors_str}
年: {paper['year']}
要旨: {paper['abstract'][:1000]}

要約:"""
                
                response = model.generate_content(prompt)
                summary = response.text
                summaries[paper['title']] = summary
                time.sleep(2)
                
            except Exception as e:
                summaries[paper['title']] = f"要約エラー: {str(e)}"
                continue
        
        return summaries
    except Exception as e:
        st.error(f"Gemini API エラー: {e}")
        return {}


# ==================== テキスト解析 ====================
def extract_keywords(text: str, min_length: int = 4, top_n: int = 50) -> List[str]:
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


# ==================== メインアプリ ====================
def main():
    st.title("🔬 Mass Spectrometry 論文研究システム")
    st.markdown("高度な論文分析・トレンド解析・AI要約システム")
    st.markdown("---")

    with st.sidebar:
        st.header("⚙️ 設定")
        gemini_key = st.text_input(
            "Google Gemini API Key",
            type="password",
            value=st.session_state.gemini_api_key,
            help="https://makersuite.google.com/app/apikey"
        )
        if gemini_key:
            st.session_state.gemini_api_key = gemini_key
            st.success("✅ APIキー設定済み")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📚 論文検索", "📈 研究トレンド", "🤖 AI一括要約",
        "📊 ワードクラウド", "🕸️ 共起ネットワーク", "💾 保存データ"
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
                            st.success(f"✅ {len(papers)}件の論文を取得しました")

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
                        st.error(f"エラー: {e}")

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

    # タブ3: AI一括要約
    with tab3:
        st.header("🤖 AI一括要約")
        if st.session_state.papers:
            if not st.session_state.gemini_api_key:
                st.warning("⚠️ サイドバーでGemini API Keyを設定してください")
                st.markdown("[Google AI Studio](https://makersuite.google.com/app/apikey)で無料取得")
            else:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.info(f"現在 {len(st.session_state.papers)} 件の論文があります")
                with col2:
                    max_summarize = st.number_input("要約する件数", 1, min(10, len(st.session_state.papers)), 5)
                
                if st.button("🤖 AI要約を開始", type="primary"):
                    papers_to_summarize = st.session_state.papers[:max_summarize]
                    with st.spinner(f"{len(papers_to_summarize)}件の論文を要約中..."):
                        summaries = summarize_papers_with_gemini(papers_to_summarize, st.session_state.gemini_api_key)
                        if summaries:
                            st.session_state.summaries = summaries
                            st.success(f"✅ {len(summaries)}件の論文を要約しました")
                            for i, (title, summary) in enumerate(summaries.items(), 1):
                                with st.expander(f"📝 {i}. {title[:70]}..."):
                                    st.markdown(f"**要約**: {summary}")
                                    original_paper = next((p for p in papers_to_summarize if p['title'] == title), None)
                                    if original_paper:
                                        st.markdown(f"**URL**: [{original_paper['url']}]({original_paper['url']})")
                        else:
                            st.error("要約に失敗しました")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ4: ワードクラウド
    with tab4:
        st.header("☁️ ワードクラウド生成")
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

    # タブ5: 共起ネットワーク
    with tab5:
        st.header("🕸️ 共起ネットワーク解析")
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

    # タブ6: 保存データ
    with tab6:
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
