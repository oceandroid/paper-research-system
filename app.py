"""
Mass Spectrometry 論文研究システム（高度分析版）
- 研究トレンドタイムライン
- AI一括要約（Gemini API）
- 引用ランキング
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
    page_title="論文検索システム",
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


# ==================== Semantic Scholar Crawler ====================
class SemanticScholarCrawler:
    """Semantic Scholar APIから論文情報を取得"""

    def __init__(self):
        self.base_url = "https://api.semanticscholar.org/graph/v1"

    def search_papers(
        self,
        keyword: str,
        max_results: int = 20,
        year_from: Optional[int] = None
    ) -> List[Dict]:
        papers = []
        try:
            search_url = f"{self.base_url}/paper/search"
            
            params = {
                'query': keyword,
                'limit': min(max_results, 100),
                'fields': 'title,authors,year,abstract,venue,citationCount,externalIds,url,publicationDate'
            }

            if year_from:
                params['year'] = f"{year_from}-"

            response = requests.get(search_url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

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
                        'abstract': paper_data.get('abstract', 'N/A'),
                        'venue': paper_data.get('venue', 'N/A'),
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


# ==================== AI要約（Gemini API） ====================
def summarize_papers_with_gemini(papers: List[Dict], api_key: str, language: str = "japanese") -> Dict[str, str]:
    """Gemini APIで論文を一括要約"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        
        summaries = {}
        
        for i, paper in enumerate(papers):
            try:
                if paper['abstract'] == 'N/A':
                    continue
                
                prompt = f"""
以下の論文を日本語で簡潔に要約してください（200文字程度）。
Mass Spectrometry分野の研究者向けに、重要なポイントを押さえてください。

タイトル: {paper['title']}
著者: {', '.join(paper['authors'][:3]) if isinstance(paper['authors'], list) else paper['authors']}
年: {paper['year']}
要旨: {paper['abstract'][:1000]}

要約:
"""
                
                response = model.generate_content(prompt)
                summary = response.text
                summaries[paper['title']] = summary
                
                time.sleep(1)  # API制限対策
                
            except Exception as e:
                summaries[paper['title']] = f"要約エラー: {str(e)}"
                continue
        
        return summaries
    
    except Exception as e:
        st.error(f"Gemini API エラー: {e}")
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
            st.success("APIキー設定済み")

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
            max_results = st.number_input("取得件数", min_value=1, max_value=50, value=10)

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
        st.markdown("論文の時系列変化とキーワードトレンドを可視化")

        if st.session_state.papers:
            st.subheader("📅 年次論文数推移")
            
            years = [p['year'] for p in st.session_state.papers if p['year'] != 'N/A' and p['year'].isdigit()]
            
            if years:
                year_counts = Counter(years)
                year_df = pd.DataFrame(
                    list(year_counts.items()),
                    columns=['年', '論文数']
                ).sort_values('年')
                
                # 折れ線グラフ
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(year_df['年'], year_df['論文数'], marker='o', linewidth=2, markersize=8)
                ax.set_xlabel('年', fontsize=12)
                ax.set_ylabel('論文数', fontsize=12)
                ax.set_title('年次論文数推移', fontsize=14, fontweight='bold')
                ax.grid(True, alpha=0.3)
                st.pyplot(fig)
                
                # 統計情報
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("総論文数", len(years))
                with col2:
                    peak_year = year_counts.most_common(1)[0][0]
                    st.metric("ピーク年", peak_year)
                with col3:
                    avg_per_year = len(years) / len(year_counts) if year_counts else 0
                    st.metric("年平均", f"{avg_per_year:.1f}件")
                
                # トレンド判定
                st.subheader("📊 トレンド分析")
                sorted_years = sorted(year_counts.items())
                if len(sorted_years) >= 3:
                    recent_3years = sum([count for year, count in sorted_years[-3:]])
                    older_3years = sum([count for year, count in sorted_years[:3]])
                    
                    if recent_3years > older_3years * 1.5:
                        st.success("🔥 **上昇トレンド**: 近年の研究が活発化しています")
                    elif recent_3years < older_3years * 0.7:
                        st.warning("📉 **減少トレンド**: 研究活動が減少傾向です")
                    else:
                        st.info("➡️ **安定トレンド**: 研究活動は安定しています")
                
                # キーワードの時系列変化
                st.subheader("🔑 キーワード出現トレンド")
                
                all_text = " ".join([
                    f"{p['title']} {p['abstract']}"
                    for p in st.session_state.papers
                    if p['abstract'] != 'N/A'
                ])
                
                top_keywords = extract_keywords(all_text, min_length=5, top_n=10)
                
                if top_keywords:
                    keyword_trends = {}
                    
                    for kw in top_keywords[:5]:  # 上位5キーワードのみ
                        yearly_count = {}
                        for paper in st.session_state.papers:
                            if paper['year'] != 'N/A' and paper['year'].isdigit():
                                text = f"{paper['title']} {paper['abstract']}".lower()
                                if kw in text:
                                    yearly_count[paper['year']] = yearly_count.get(paper['year'], 0) + 1
                        
                        keyword_trends[kw] = yearly_count
                    
                    # キーワード別折れ線グラフ
                    fig, ax = plt.subplots(figsize=(12, 6))
                    
                    for kw, trend in keyword_trends.items():
                        sorted_trend = sorted(trend.items())
                        years_list = [year for year, _ in sorted_trend]
                        counts_list = [count for _, count in sorted_trend]
                        ax.plot(years_list, counts_list, marker='o', label=kw, linewidth=2)
                    
                    ax.set_xlabel('年', fontsize=12)
                    ax.set_ylabel('出現回数', fontsize=12)
                    ax.set_title('キーワード出現トレンド（上位5件）', fontsize=14, fontweight='bold')
                    ax.legend()
                    ax.grid(True, alpha=0.3)
                    st.pyplot(fig)
                
            else:
                st.warning("年データが不足しています")
        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ3: AI一括要約
    with tab3:
        st.header("🤖 AI一括要約（Gemini API）")
        st.markdown("取得した論文をAIが自動で要約します")

        if st.session_state.papers:
            if not st.session_state.gemini_api_key:
                st.warning("⚠️ サイドバーでGemini API Keyを設定してください")
                st.markdown("[Google AI Studio](https://makersuite.google.com/app/apikey)で無料で取得できます")
            else:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.info(f"現在 {len(st.session_state.papers)} 件の論文があります")
                with col2:
                    max_summarize = st.number_input("要約する件数", 1, min(20, len(st.session_state.papers)), 5)
                
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
                            
                            # 要約結果を表示
                            for i, (title, summary) in enumerate(summaries.items(), 1):
                                with st.expander(f"📝 {i}. {title[:70]}..."):
                                    st.markdown(f"**要約**:")
                                    st.markdown(summary)
                                    
                                    # 元論文の情報も表示
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
                    text = " ".join([
                        f"{p['title']} {p['abstract']}"
                        for p in st.session_state.papers
                        if p['abstract'] != 'N/A'
                    ])

                    if text:
                        wordcloud = WordCloud(
                            width=1200,
                            height=600,
                            background_color='white',
                            colormap='viridis',
                            max_words=max_words
                        ).generate(text)

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
                    keywords, cooccurrence = build_cooccurrence_network(
                        st.session_state.papers,
                        top_keywords=top_keywords,
                        window_size=window_size
                    )

                    G = nx.Graph()
                    
                    for (word1, word2), count in cooccurrence.items():
                        if count >= min_cooccurrence:
                            G.add_edge(word1, word2, weight=count)

                    if len(G.nodes()) > 0:
                        pos = nx.spring_layout(G, k=0.5, iterations=50)
                        fig, ax = plt.subplots(figsize=(16, 12))
                        
                        node_sizes = [G.degree(node) * 300 for node in G.nodes()]
                        nx.draw_networkx_nodes(
                            G, pos,
                            node_size=node_sizes,
                            node_color='lightblue',
                            alpha=0.7,
                            ax=ax
                        )

                        edges = G.edges()
                        weights = [G[u][v]['weight'] for u, v in edges]
                        max_weight = max(weights) if weights else 1
                        
                        nx.draw_networkx_edges(
                            G, pos,
                            width=[w / max_weight * 5 for w in weights],
                            alpha=0.3,
                            ax=ax
                        )

                        nx.draw_networkx_labels(
                            G, pos,
                            font_size=10,
                            font_weight='bold',
                            ax=ax
                        )

                        ax.axis('off')
                        ax.set_title(
                            f"共起ネットワーク (ノード数: {len(G.nodes())}, エッジ数: {len(G.edges())})",
                            fontsize=16
                        )
                        
                        st.pyplot(fig)
                        
                        st.subheader("📊 ネットワーク統計")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("ノード数", len(G.nodes()))
                        with col2:
                            st.metric("エッジ数", len(G.edges()))
                        with col3:
                            if len(G.nodes()) > 0:
                                avg_degree = sum(dict(G.degree()).values()) / len(G.nodes())
                                st.metric("平均次数", f"{avg_degree:.2f}")

                        st.success("✅ 共起ネットワーク生成完了")
                    else:
                        st.warning("共起関係が見つかりませんでした")

        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ6: 保存データ
    with tab6:
        st.header("💾 保存されたデータ")

        if st.session_state.papers:
            # 引用ランキング
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
                        st.metric("引用数", paper['citations'])
            else:
                st.info("引用数データがありません（PubMedは引用数なし）")
            
            st.markdown("---")
            
            # 論文リスト
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
                    'タイトル': p['title'][:60] + '...' if len(p['title']) > 60 else p['title'],
                    '著者': authors_str,
                    '年': p['year'],
                    'ソース': p.get('source', 'N/A'),
                    '引用': p.get('citations', 0)
                })
            
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True)

            # CSV ダウンロード
            csv = pd.DataFrame(st.session_state.papers).to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 CSV形式でダウンロード",
                data=csv,
                file_name=f"papers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

            # 統計情報
            st.subheader("📊 統計情報")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("総論文数", len(st.session_state.papers))
            
            with col2:
                years = [p['year'] for p in st.session_state.papers if p['year'] != 'N/A']
                if years:
                    year_counts = Counter(years)
                    most_common_year = year_counts.most_common(1)[0][0]
                    st.metric("最多発表年", most_common_year)
            
            with col3:
                if years:
                    st.metric("最新年", max(years))
            
            with col4:
                total_citations = sum([p.get('citations', 0) for p in st.session_state.papers])
                st.metric("総引用数", total_citations)

        else:
            st.info("まだデータがありません")


if __name__ == "__main__":
    main()
