"""
Mass Spectrometry 論文研究システム（機能拡張版）
- PubMed & Google Scholar 対応
- ワードクラウド & 共起ネットワーク解析
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


# ==================== Google Scholar Crawler ====================
class ScholarCrawler:
    """Google Scholarから論文情報を取得（scholarly使用）"""

    def __init__(self):
        self.results = []
        # scholarly のインポートを遅延実行
        try:
            from scholarly import scholarly, ProxyGenerator
            self.scholarly = scholarly
            
            # プロキシ設定（ブロック対策）
            try:
                pg = ProxyGenerator()
                pg.FreeProxies()
                scholarly.use_proxy(pg)
            except:
                pass  # プロキシ設定失敗してもスキップ
        except ImportError:
            st.error("scholarly ライブラリがインストールされていません")
            self.scholarly = None

    def search_papers(
        self,
        keyword: str,
        max_results: int = 20,
        year_from: Optional[int] = None
    ) -> List[Dict]:
        if not self.scholarly:
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
                    time.sleep(2)  # Rate limit対策

                except Exception as e:
                    continue

            return papers

        except Exception as e:
            st.error(f"Google Scholar エラー: {e}")
            st.info("💡 Google Scholarがブロックされた可能性があります。PubMedをお試しください。")
            return papers

    def get_recent_papers(self, keyword: str, days: int = 7, max_results: int = 20) -> List[Dict]:
        current_year = datetime.now().year
        target_date = datetime.now() - timedelta(days=days)
        year_from = target_date.year
        return self.search_papers(keyword, max_results, year_from)


# ==================== テキスト解析ユーティリティ ====================
def extract_keywords(text: str, min_length: int = 4, top_n: int = 50) -> List[str]:
    """テキストからキーワードを抽出"""
    # 英単語のみ抽出（小文字化）
    words = re.findall(r'\b[a-zA-Z]{' + str(min_length) + r',}\b', text.lower())
    
    # ストップワードを除外
    stop_words = {
        'this', 'that', 'with', 'from', 'were', 'been', 'have', 'has', 'had',
        'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can',
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
        'was', 'said', 'them', 'been', 'than', 'find', 'also', 'made',
        'when', 'what', 'which', 'their', 'these', 'those', 'such', 'into',
        'through', 'during', 'before', 'after', 'about', 'between', 'under'
    }
    
    filtered_words = [w for w in words if w not in stop_words]
    
    # 頻度カウント
    word_counts = Counter(filtered_words)
    return [word for word, _ in word_counts.most_common(top_n)]


def build_cooccurrence_network(papers: List[Dict], top_keywords: int = 30, window_size: int = 10):
    """共起ネットワークを構築"""
    # 全テキストを結合
    all_text = " ".join([
        f"{p['title']} {p['abstract']}"
        for p in papers
        if p['abstract'] != 'N/A'
    ])
    
    # キーワード抽出
    keywords = extract_keywords(all_text, min_length=5, top_n=top_keywords)
    
    # 共起行列を作成
    cooccurrence = Counter()
    
    for paper in papers:
        text = f"{paper['title']} {paper['abstract']}"
        words = re.findall(r'\b[a-zA-Z]{5,}\b', text.lower())
        
        # ウィンドウ内での共起をカウント
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
    st.markdown("PubMed・Google Scholarから論文を検索し、高度な解析が可能なシステム")
    st.markdown("---")

    # タブ
    tab1, tab2, tab3, tab4 = st.tabs(["📚 論文検索", "📊 ワードクラウド", "🕸️ 共起ネットワーク", "💾 保存データ"])

    # タブ1: 論文検索
    with tab1:
        st.header("論文検索")

        # データソース選択
        data_source = st.radio(
            "データソース",
            ["PubMed（推奨・安定）", "Google Scholar"],
            help="PubMedは公式APIで安定。Google Scholarは引用数も取得できるがブロックされる可能性あり"
        )

        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input(
                "検索キーワード",
                placeholder="例: mass spectrometry proteomics",
                help="検索するキーワードを入力"
            )
        with col2:
            max_results = st.number_input("取得件数", min_value=1, max_value=50, value=10)

        col3, col4 = st.columns(2)
        with col3:
            year_from = st.number_input("検索開始年", min_value=2000, max_value=2030, value=2020)
        with col4:
            search_mode = st.selectbox("検索モード", ["通常検索", "最近の論文（直近7日）"])

        if st.button("🔍 検索開始", type="primary"):
            if not query:
                st.warning("検索キーワードを入力してください")
            else:
                with st.spinner(f"{data_source}で論文を検索中..."):
                    try:
                        # データソースに応じてクローラーを選択
                        if data_source == "PubMed（推奨・安定）":
                            crawler = PubMedCrawler()
                        else:
                            crawler = ScholarCrawler()

                        if search_mode == "通常検索":
                            papers = crawler.search_papers(query, max_results, year_from)
                        else:
                            papers = crawler.get_recent_papers(query, days=7, max_results=max_results)

                        if papers:
                            st.session_state.papers = papers
                            st.success(f"✅ {len(papers)}件の論文を取得しました（ソース: {data_source}）")

                            # 結果を表示
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
                        if data_source == "Google Scholar":
                            st.info("💡 Google Scholarでエラーが出た場合は、PubMedをお試しください")

    # タブ2: ワードクラウド
    with tab2:
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

    # タブ3: 共起ネットワーク
    with tab3:
        st.header("🕸️ 共起ネットワーク解析")
        st.markdown("キーワード間の関係性を可視化します")

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

                    # ネットワークグラフを構築
                    G = nx.Graph()
                    
                    for (word1, word2), count in cooccurrence.items():
                        if count >= min_cooccurrence:
                            G.add_edge(word1, word2, weight=count)

                    if len(G.nodes()) > 0:
                        # レイアウト計算
                        pos = nx.spring_layout(G, k=0.5, iterations=50)

                        # 描画
                        fig, ax = plt.subplots(figsize=(16, 12))
                        
                        # ノード描画
                        node_sizes = [G.degree(node) * 300 for node in G.nodes()]
                        nx.draw_networkx_nodes(
                            G, pos,
                            node_size=node_sizes,
                            node_color='lightblue',
                            alpha=0.7,
                            ax=ax
                        )

                        # エッジ描画
                        edges = G.edges()
                        weights = [G[u][v]['weight'] for u, v in edges]
                        max_weight = max(weights) if weights else 1
                        
                        nx.draw_networkx_edges(
                            G, pos,
                            width=[w / max_weight * 5 for w in weights],
                            alpha=0.3,
                            ax=ax
                        )

                        # ラベル描画
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
                        
                        # 統計情報
                        st.subheader("📊 ネットワーク統計")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("ノード数（キーワード）", len(G.nodes()))
                        with col2:
                            st.metric("エッジ数（共起関係）", len(G.edges()))
                        with col3:
                            if len(G.nodes()) > 0:
                                avg_degree = sum(dict(G.degree()).values()) / len(G.nodes())
                                st.metric("平均次数", f"{avg_degree:.2f}")

                        # 中心性の高いキーワード
                        st.subheader("🎯 重要キーワード（中心性順）")
                        if len(G.nodes()) > 0:
                            degree_centrality = nx.degree_centrality(G)
                            top_central = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:10]
                            
                            df_central = pd.DataFrame(top_central, columns=['キーワード', '中心性'])
                            st.dataframe(df_central, use_container_width=True)

                        st.success("✅ 共起ネットワーク生成完了")
                    else:
                        st.warning("共起関係が見つかりませんでした。最小共起回数を下げてみてください。")

        else:
            st.info("まず「論文検索」タブで論文を取得してください")

    # タブ4: 保存データ
    with tab4:
        st.header("💾 保存されたデータ")

        if st.session_state.papers:
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

            # データソース別集計
            st.subheader("📈 データソース別")
            sources = [p.get('source', 'Unknown') for p in st.session_state.papers]
            source_counts = Counter(sources)
            
            df_sources = pd.DataFrame(source_counts.items(), columns=['ソース', '論文数'])
            st.bar_chart(df_sources.set_index('ソース'))

        else:
            st.info("まだデータがありません。「論文検索」タブから始めてください。")

    # サイドバー
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📖 使い方")
    st.sidebar.markdown("""
    **1. 論文検索**
    - PubMed/Google Scholarを選択
    - キーワードを入力して検索
    
    **2. ワードクラウド**
    - 頻出単語を視覚化
    
    **3. 共起ネットワーク**
    - キーワード間の関係性を解析
    - ノードサイズ = 重要度
    - エッジの太さ = 共起頻度
    
    **4. データ保存**
    - CSV形式でダウンロード可能
    """)
    st.sidebar.markdown("---")
    st.sidebar.info("💡 セッション中のみデータを保持します")


if __name__ == "__main__":
    main()
