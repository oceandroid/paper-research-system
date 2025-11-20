"""
Streamlitによる論文研究システムのUIアプリケーション
"""
import streamlit as st
import sys
import os
import json
from datetime import datetime, timedelta
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import pandas as pd
from collections import Counter

# パスを追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import DatabaseManager
from crawler.scholar_crawler import ScholarCrawler
from crawler.pubmed_crawler import PubMedCrawler
from analyzer.llm_analyzer import LLMAnalyzer


# ページ設定
st.set_page_config(
    page_title="論文研究システム",
    page_icon="📚",
    layout="wide"
)


@st.cache_resource
def get_db():
    """データベースマネージャーのシングルトン"""
    return DatabaseManager("papers.db")


@st.cache_resource
def get_analyzer():
    """LLM解析器のシングルトン"""
    return LLMAnalyzer()


def main():
    st.title("📚 論文研究システム")
    st.markdown("---")

    # サイドバー
    with st.sidebar:
        st.header("メニュー")
        page = st.radio(
            "ページ選択",
            ["ホーム", "論文検索・クローリング", "データベース閲覧", "解析・可視化", "設定"]
        )

    db = get_db()

    # ページ表示
    if page == "ホーム":
        show_home(db)
    elif page == "論文検索・クローリング":
        show_crawling_page(db)
    elif page == "データベース閲覧":
        show_database_page(db)
    elif page == "解析・可視化":
        show_analysis_page(db)
    elif page == "設定":
        show_settings_page()


def show_home(db):
    """ホームページ"""
    st.header("📊 ダッシュボード")

    # 統計情報
    papers = db.get_all_papers()
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("総論文数", len(papers))

    with col2:
        recent_logs = db.get_recent_crawls(limit=1)
        last_crawl = recent_logs[0].executed_at.strftime("%Y-%m-%d %H:%M") if recent_logs else "未実行"
        st.metric("最終クローリング", last_crawl)

    with col3:
        # 最新の論文
        if papers:
            latest_year = max([p.year for p in papers if p.year != 'N/A'])
            st.metric("最新論文年", latest_year)

    st.markdown("---")

    # 最近のクローリング履歴
    st.subheader("🔄 最近のクローリング履歴")
    logs = db.get_recent_crawls(limit=5)

    if logs:
        log_data = []
        for log in logs:
            log_data.append({
                "実行日時": log.executed_at.strftime("%Y-%m-%d %H:%M:%S"),
                "キーワード": log.keyword,
                "取得数": log.papers_count,
                "ステータス": log.status
            })
        st.dataframe(pd.DataFrame(log_data), use_container_width=True)
    else:
        st.info("クローリング履歴がありません")

    st.markdown("---")

    # 最新論文
    st.subheader("📄 最新の論文（5件）")
    recent_papers = db.get_all_papers(limit=5)

    if recent_papers:
        for paper in recent_papers:
            with st.expander(f"**{paper.title}** ({paper.year})"):
                st.write(f"**著者:** {paper.authors}")
                st.write(f"**掲載:** {paper.venue}")
                st.write(f"**引用数:** {paper.citations}")
                st.write(f"**URL:** {paper.url}")
                if paper.abstract != 'N/A':
                    st.write(f"**概要:** {paper.abstract[:300]}...")
    else:
        st.info("まだ論文が登録されていません。「論文検索・クローリング」から論文を取得してください。")


def show_crawling_page(db):
    """論文クローリングページ"""
    st.header("🔍 論文検索・クローリング")

    # データソース選択
    data_source = st.radio(
        "データソース",
        ["PubMed（推奨・安定）", "Google Scholar"],
        help="PubMedは公式APIで安定、Google Scholarはブロックされる可能性あり"
    )

    col1, col2 = st.columns(2)

    with col1:
        keyword = st.text_input("検索キーワード", value="mass spectrometry")
        max_results = st.slider("取得件数", min_value=5, max_value=50, value=10)

    with col2:
        year_from = st.number_input("検索開始年", min_value=2000, max_value=2030, value=2024)
        search_mode = st.selectbox("検索モード", ["通常検索", "最近の論文（直近7日）"])

    if st.button("🚀 検索開始", type="primary"):
        with st.spinner("論文を検索中..."):
            try:
                # データソースに応じてクローラーを選択
                if data_source == "PubMed（推奨・安定）":
                    crawler = PubMedCrawler(email="user@example.com")
                else:
                    crawler = ScholarCrawler()

                if search_mode == "通常検索":
                    papers = crawler.search_papers(keyword, max_results, year_from)
                else:
                    papers = crawler.get_recent_papers(keyword, days=7, max_results=max_results)

                if papers:
                    st.success(f"✅ {len(papers)}件の論文を取得しました（ソース: {data_source}）")

                    # データベースに保存
                    saved_count = db.save_papers(papers)
                    db.log_crawl(keyword, saved_count, "success")

                    st.info(f"💾 {saved_count}件の新規論文をデータベースに保存しました")

                    # 結果を表示
                    for i, paper in enumerate(papers[:5], 1):
                        with st.expander(f"{i}. {paper['title'][:80]}..."):
                            st.write(f"**著者:** {', '.join(paper['authors'][:3]) if isinstance(paper['authors'], list) else paper['authors']}")
                            st.write(f"**年:** {paper['year']}")
                            st.write(f"**引用数:** {paper['citations']}")
                            st.write(f"**ジャーナル:** {paper.get('venue', 'N/A')}")
                            st.write(f"**URL:** [{paper['url']}]({paper['url']})")
                            if paper.get('abstract') and paper['abstract'] != 'N/A':
                                st.write(f"**要旨:** {paper['abstract'][:300]}...")
                else:
                    st.warning("論文が見つかりませんでした")
                    db.log_crawl(keyword, 0, "failed", "No papers found")

            except Exception as e:
                st.error(f"❌ エラーが発生しました: {e}")
                st.info("💡 Google Scholarでエラーが出た場合は、PubMedをお試しください")
                db.log_crawl(keyword, 0, "failed", str(e))


def show_database_page(db):
    """データベース閲覧ページ"""
    st.header("💾 データベース閲覧")

    # 検索フィルター
    col1, col2 = st.columns(2)
    with col1:
        keyword_filter = st.text_input("キーワードでフィルター", "")
    with col2:
        limit = st.number_input("表示件数", min_value=10, max_value=100, value=20)

    # 論文取得
    if keyword_filter:
        papers = db.get_papers_by_keyword(keyword_filter)
    else:
        papers = db.get_all_papers(limit=limit)

    st.write(f"**表示件数:** {len(papers)}件")

    if papers:
        for paper in papers:
            with st.expander(f"**{paper.title}** ({paper.year})"):
                col1, col2 = st.columns([3, 1])

                with col1:
                    authors_list = json.loads(paper.authors) if paper.authors.startswith('[') else paper.authors
                    authors_str = ', '.join(authors_list) if isinstance(authors_list, list) else authors_list

                    st.write(f"**著者:** {authors_str}")
                    st.write(f"**掲載:** {paper.venue}")
                    st.write(f"**URL:** {paper.url}")
                    if paper.abstract != 'N/A':
                        st.write(f"**概要:** {paper.abstract}")

                with col2:
                    st.metric("引用数", paper.citations)
                    st.write(f"登録日: {paper.created_at.strftime('%Y-%m-%d')}")

                # 解析ボタン
                if st.button(f"この論文を解析", key=f"analyze_{paper.id}"):
                    analyze_single_paper(db, paper)
    else:
        st.info("論文がありません")


def analyze_single_paper(db, paper):
    """単一の論文を解析"""
    analyzer = get_analyzer()

    with st.spinner("論文を解析中..."):
        # 著者情報を整形
        authors_list = json.loads(paper.authors) if paper.authors.startswith('[') else paper.authors
        authors_str = ', '.join(authors_list) if isinstance(authors_list, list) else authors_list

        analysis = analyzer.analyze_paper(
            title=paper.title,
            abstract=paper.abstract,
            authors=authors_str,
            year=paper.year
        )

        # データベースに保存
        db.save_analysis(paper.id, analysis)

        st.success("解析完了！")
        st.json(analysis)


def show_analysis_page(db):
    """解析・可視化ページ"""
    st.header("📊 解析・可視化")

    papers = db.get_all_papers()

    if not papers:
        st.warning("論文がありません。まず論文をクローリングしてください。")
        return

    tab1, tab2, tab3 = st.tabs(["ワードクラウド", "統計分析", "一括解析"])

    with tab1:
        st.subheader("☁️ ワードクラウド")

        # アブストラクトからテキストを抽出
        all_text = " ".join([
            paper.abstract for paper in papers
            if paper.abstract and paper.abstract != 'N/A'
        ])

        if all_text:
            try:
                # ワードクラウド生成
                wordcloud = WordCloud(
                    width=800,
                    height=400,
                    background_color='white',
                    colormap='viridis',
                    max_words=100
                ).generate(all_text)

                # 表示
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.imshow(wordcloud, interpolation='bilinear')
                ax.axis('off')
                st.pyplot(fig)

            except Exception as e:
                st.error(f"ワードクラウド生成エラー: {e}")
        else:
            st.info("アブストラクトデータが不足しています")

    with tab2:
        st.subheader("📈 統計分析")

        # 年別論文数
        years = [p.year for p in papers if p.year != 'N/A']
        year_counts = Counter(years)

        if year_counts:
            st.write("**年別論文数**")
            year_df = pd.DataFrame(
                list(year_counts.items()),
                columns=['年', '論文数']
            ).sort_values('年')
            st.bar_chart(year_df.set_index('年'))

        # 引用数上位
        st.write("**引用数トップ10**")
        papers_sorted = sorted(papers, key=lambda x: x.citations, reverse=True)[:10]
        citation_data = [{
            'タイトル': p.title[:50] + '...' if len(p.title) > 50 else p.title,
            '引用数': p.citations,
            '年': p.year
        } for p in papers_sorted]
        st.dataframe(pd.DataFrame(citation_data), use_container_width=True)

    with tab3:
        st.subheader("🔬 全体傾向の要約")
        st.write("データベース内の論文全体の研究トレンドをAIで分析します")

        # Gemini APIキーの入力
        api_key = st.text_input("Google Gemini APIキー", type="password",
                               help="https://makersuite.google.com/app/apikey から取得",
                               key="gemini_api_key")

        limit = st.slider("解析する論文数", min_value=5, max_value=50, value=20)

        if st.button("全体傾向を分析", type="primary"):
            if not api_key:
                st.error("⚠️ Gemini APIキーを入力してください")
                st.info("無料APIキーは https://makersuite.google.com/app/apikey から取得できます")
            else:
                papers_to_analyze = db.get_all_papers(limit=limit)

                if not papers_to_analyze:
                    st.warning("論文がありません。まずクローリングしてください。")
                else:
                    with st.spinner(f"{len(papers_to_analyze)}件の論文を分析中..."):
                        try:
                            import google.generativeai as genai

                            # Gemini API設定
                            genai.configure(api_key=api_key)

                            # モデル選択（フォールバック付き）
                            try:
                                model = genai.GenerativeModel('gemini-1.5-pro-latest')
                            except:
                                try:
                                    model = genai.GenerativeModel('gemini-1.5-flash')
                                except:
                                    model = genai.GenerativeModel('gemini-pro')

                            # 論文データを集約
                            papers_summary = []
                            for i, paper in enumerate(papers_to_analyze, 1):
                                abstract = paper.abstract if paper.abstract != 'N/A' else "No abstract"
                                papers_summary.append(f"{i}. {paper.title} ({paper.year})\n   概要: {abstract[:200]}...")

                            combined_text = "\n\n".join(papers_summary)

                            # プロンプト作成
                            prompt = f"""以下の{len(papers_to_analyze)}件の質量分析（Mass Spectrometry）関連論文を分析し、研究全体の傾向を日本語で要約してください。

【論文リスト】
{combined_text}

【分析項目】
1. **主要な研究テーマ**: どのような研究テーマが中心か？
2. **使用されている手法**: 共通して用いられている分析手法や技術は？
3. **研究の時系列トレンド**: 年代によって研究の焦点がどう変化しているか？
4. **注目すべきキーワード**: 頻出する重要なキーワードは？
5. **今後の研究方向性**: これらの論文から見える今後の研究の方向性は？

各項目について、3-5文程度で簡潔に説明してください。"""

                            # API呼び出し
                            response = model.generate_content(prompt)

                            # 結果表示
                            st.success("✅ 分析完了！")
                            st.markdown("---")
                            st.markdown("### 📊 研究トレンド分析結果")
                            st.markdown(response.text)

                            # 基本統計も表示
                            st.markdown("---")
                            st.markdown("### 📈 基本統計")
                            col1, col2, col3 = st.columns(3)

                            with col1:
                                st.metric("分析論文数", len(papers_to_analyze))

                            with col2:
                                years = [p.year for p in papers_to_analyze if p.year != 'N/A']
                                if years:
                                    year_range = f"{min(years)}-{max(years)}"
                                    st.metric("対象年範囲", year_range)

                            with col3:
                                total_citations = sum([p.citations for p in papers_to_analyze])
                                st.metric("総引用数", total_citations)

                        except Exception as e:
                            st.error(f"❌ エラーが発生しました: {e}")
                            st.info("💡 APIキーが正しいか確認してください。また、Gemini APIの利用制限に達していないか確認してください。")


def show_settings_page():
    """設定ページ"""
    st.header("⚙️ 設定")

    st.subheader("API設定")
    st.write("環境変数 `OPENAI_API_KEY` を設定してください")

    api_key = st.text_input("OpenAI APIキー", type="password", placeholder="sk-...")

    if api_key:
        st.success("APIキーが入力されました（.envファイルに保存してください）")

        # .envファイルに保存する例
        if st.button("環境変数として保存"):
            env_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                '.env'
            )
            with open(env_path, 'w') as f:
                f.write(f"OPENAI_API_KEY={api_key}\n")
            st.success(f".envファイルに保存しました: {env_path}")

    st.markdown("---")
    st.subheader("スケジューラー設定")
    st.write("定期実行の設定は `scheduler/scheduler.py` を編集してください")


if __name__ == "__main__":
    main()
