"""
論文研究システム
"""
import streamlit as st
import sys
import os
from datetime import datetime
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import pandas as pd
from collections import Counter
import time
import requests
from typing import List, Dict, Optional
from xml.etree import ElementTree as ET

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
            # 検索してPubMed IDを取得
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

            # 詳細情報を取得
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
                    except Exception as e:
                        continue

                time.sleep(0.5)

            return papers

        except Exception as e:
            st.error(f"PubMed API エラー: {e}")
            return papers

    def _extract_paper_info(self, article_xml, keyword: str) -> Dict:
        # タイトル
        title_elem = article_xml.find('.//ArticleTitle')
        title = title_elem.text if title_elem is not None else 'N/A'

        # 著者
        authors = []
        for author in article_xml.findall('.//Author'):
            lastname = author.find('LastName')
            forename = author.find('ForeName')
            if lastname is not None:
                name = lastname.text
                if forename is not None:
                    name = f"{forename.text} {name}"
                authors.append(name)

        # 発表年
        year_elem = article_xml.find('.//PubDate/Year')
        year = year_elem.text if year_elem is not None else 'N/A'

        # アブストラクト
        abstract_texts = []
        for abstract in article_xml.findall('.//AbstractText'):
            if abstract.text:
                abstract_texts.append(abstract.text)
        abstract = ' '.join(abstract_texts) if abstract_texts else 'N/A'

        # ジャーナル名
        journal_elem = article_xml.find('.//Journal/Title')
        venue = journal_elem.text if journal_elem is not None else 'N/A'

        # PubMed ID
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


# ==================== メインアプリ ====================
def main():
    st.title("🔬 Mass Spectrometry 論文研究システム")
    st.markdown("PubMedから論文を検索・要約できるシステムです")
    st.markdown("---")

    # タブ
    tab1, tab2, tab3 = st.tabs(["📚 論文検索", "📊 ワードクラウド", "💾 保存データ"])

    # タブ1: 論文検索
    with tab1:
        st.header("論文検索")

        col1, col2 = st.columns([3, 1])
        with col1:
            query = st.text_input(
                "検索キーワード",
                placeholder="例: mass spectrometry proteomics",
                help="PubMedで検索するキーワードを入力"
            )
        with col2:
            max_results = st.number_input("取得件数", min_value=1, max_value=50, value=10)

        col3, col4 = st.columns(2)
        with col3:
            year_from = st.number_input("検索開始年", min_value=2000, max_value=2030, value=2024)
        with col4:
            search_mode = st.selectbox("検索モード", ["通常検索", "最近の論文（直近7日）"])

        if st.button("🔍 検索開始", type="primary"):
            if not query:
                st.warning("検索キーワードを入力してください")
            else:
                with st.spinner("論文を検索中..."):
                    try:
                        crawler = PubMedCrawler()

                        if search_mode == "通常検索":
                            papers = crawler.search_papers(query, max_results, year_from)
                        else:
                            papers = crawler.get_recent_papers(query, days=7, max_results=max_results)

                        if papers:
                            st.session_state.papers = papers
                            st.success(f"✅ {len(papers)}件の論文を取得しました（ソース: PubMed）")

                            # 結果を表示
                            for i, paper in enumerate(papers[:10], 1):
                                with st.expander(f"📄 {i}. {paper['title'][:80]}..."):
                                    authors_str = ', '.join(paper['authors'][:3]) if len(paper['authors']) > 3 else ', '.join(paper['authors'])
                                    st.markdown(f"**著者**: {authors_str}")
                                    st.markdown(f"**発表年**: {paper['year']} | **ジャーナル**: {paper['venue']}")
                                    st.markdown(f"**URL**: [{paper['url']}]({paper['url']})")
                                    if paper['abstract'] != 'N/A':
                                        st.markdown(f"**要旨**: {paper['abstract'][:400]}...")
                        else:
                            st.warning("論文が見つかりませんでした")

                    except Exception as e:
                        st.error(f"エラーが発生しました: {e}")

    # タブ2: ワードクラウド
    with tab2:
        st.header("ワードクラウド生成")

        if st.session_state.papers:
            if st.button("☁️ ワードクラウドを生成"):
                with st.spinner("生成中..."):
                    # 全論文のタイトルと要旨を結合
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
                            max_words=100
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

    # タブ3: 保存データ
    with tab3:
        st.header("保存されたデータ")

        if st.session_state.papers:
            st.subheader("📚 取得済み論文")
            
            # データフレーム作成
            df_data = []
            for p in st.session_state.papers:
                authors_str = ', '.join(p['authors'][:2]) if len(p['authors']) > 2 else ', '.join(p['authors'])
                df_data.append({
                    'タイトル': p['title'][:60] + '...' if len(p['title']) > 60 else p['title'],
                    '著者': authors_str,
                    '年': p['year'],
                    'ジャーナル': p['venue'][:40] + '...' if len(p.get('venue', '')) > 40 else p.get('venue', 'N/A')
                })
            
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True)

            # CSV ダウンロード
            csv = pd.DataFrame(st.session_state.papers).to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 CSV形式でダウンロード",
                data=csv,
                file_name=f"papers_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

            # 統計情報
            st.subheader("📊 統計情報")
            col1, col2, col3 = st.columns(3)
            
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

        else:
            st.info("まだデータがありません。「論文検索」タブから始めてください。")

    # フッター
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📖 使い方")
    st.sidebar.markdown("""
    1. 検索キーワードを入力
    2. 取得件数と年を設定
    3. 「検索開始」をクリック
    4. ワードクラウドで可視化
    5. CSVでダウンロード可能
    """)
    st.sidebar.markdown("---")
    st.sidebar.info("💡 セッション中のみデータを保持します。ブラウザを閉じるとリセットされます。")


if __name__ == "__main__":
    main()
