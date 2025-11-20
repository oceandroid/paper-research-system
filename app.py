import streamlit as st
import google.generativeai as genai
from scholarly import scholarly
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import re
import time

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

# タイトル
st.title("🔬 Mass Spectrometry 論文研究システム")
st.markdown("Google Scholarから論文を検索し、AIで日本語要約を生成します")

# サイドバー: API設定
st.sidebar.header("⚙️ 設定")
gemini_api_key = st.sidebar.text_input(
    "Google Gemini API Key",
    type="password",
    help="https://makersuite.google.com/app/apikey で取得できます（無料）"
)

if gemini_api_key:
    genai.configure(api_key=gemini_api_key)

# メインエリア
tab1, tab2, tab3 = st.tabs(["📚 論文検索", "📊 ワードクラウド", "💾 保存データ"])

# タブ1: 論文検索
with tab1:
    st.header("論文検索")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "検索キーワード",
            placeholder="例: mass spectrometry proteomics",
            help="Google Scholarで検索するキーワードを入力"
        )
    with col2:
        max_results = st.number_input("取得件数", min_value=1, max_value=20, value=5)

    if st.button("🔍 検索開始", type="primary", disabled=not gemini_api_key):
        if not query:
            st.warning("検索キーワードを入力してください")
        else:
            with st.spinner("論文を検索中..."):
                try:
                    # Google Scholarから論文を取得
                    search_query = scholarly.search_pubs(query)
                    papers = []

                    progress_bar = st.progress(0)
                    for i in range(max_results):
                        try:
                            paper = next(search_query)
                            papers.append({
                                'title': paper.get('bib', {}).get('title', 'タイトル不明'),
                                'author': paper.get('bib', {}).get('author', ['著者不明'])[0] if paper.get('bib', {}).get('author') else '著者不明',
                                'year': paper.get('bib', {}).get('pub_year', '年不明'),
                                'abstract': paper.get('bib', {}).get('abstract', '要旨なし'),
                                'url': paper.get('pub_url', ''),
                                'cited_by': paper.get('num_citations', 0)
                            })
                            progress_bar.progress((i + 1) / max_results)
                            time.sleep(1)  # Rate limit対策
                        except StopIteration:
                            break
                        except Exception as e:
                            st.warning(f"論文 {i+1} の取得に失敗: {str(e)}")
                            continue

                    st.session_state.papers = papers
                    st.success(f"✅ {len(papers)}件の論文を取得しました")

                except Exception as e:
                    st.error(f"検索エラー: {str(e)}")
                    st.info("💡 ヒント: 会社のプロキシでブロックされている可能性があります。別のネットワークで試してみてください。")

    # 検索結果表示
    if st.session_state.papers:
        st.subheader(f"検索結果 ({len(st.session_state.papers)}件)")

        for idx, paper in enumerate(st.session_state.papers):
            with st.expander(f"📄 {paper['title'][:100]}..."):
                st.markdown(f"**著者**: {paper['author']}")
                st.markdown(f"**発表年**: {paper['year']} | **引用数**: {paper['cited_by']}")
                st.markdown(f"**要旨**: {paper['abstract'][:300]}...")

                if paper['url']:
                    st.markdown(f"[🔗 論文リンク]({paper['url']})")

                # AI要約ボタン
                if st.button(f"🤖 AI要約を生成", key=f"summarize_{idx}"):
                    if not gemini_api_key:
                        st.warning("Gemini API Keyを入力してください")
                    else:
                        with st.spinner("要約生成中..."):
                            try:
                                model = genai.GenerativeModel('gemini-pro')
                                prompt = f"""
以下の論文情報を日本語で簡潔に要約してください（300文字程度）。
Mass Spectrometry分野の研究者向けに、重要なポイントを押さえてください。

タイトル: {paper['title']}
要旨: {paper['abstract']}

要約:
"""
                                response = model.generate_content(prompt)
                                summary = response.text

                                st.session_state.summaries[paper['title']] = {
                                    'summary': summary,
                                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                st.success("要約生成完了！")
                                st.markdown(f"**📝 AI要約**:\n\n{summary}")

                            except Exception as e:
                                st.error(f"要約生成エラー: {str(e)}")

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
                ])

                # ワードクラウド生成
                wordcloud = WordCloud(
                    width=800,
                    height=400,
                    background_color='white',
                    colormap='viridis',
                    max_words=100
                ).generate(text)

                # 表示
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.imshow(wordcloud, interpolation='bilinear')
                ax.axis('off')
                st.pyplot(fig)

                st.success("✅ ワードクラウド生成完了")
    else:
        st.info("まず「論文検索」タブで論文を取得してください")

# タブ3: 保存データ
with tab3:
    st.header("保存されたデータ")

    if st.session_state.papers:
        # 論文リスト
        st.subheader("📚 取得済み論文")
        df = pd.DataFrame(st.session_state.papers)
        st.dataframe(df[['title', 'author', 'year', 'cited_by']], use_container_width=True)

        # CSV ダウンロード
        csv = df.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 CSVダウンロード",
            data=csv,
            file_name=f"papers_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

    if st.session_state.summaries:
        st.subheader("📝 生成済みAI要約")
        for title, data in st.session_state.summaries.items():
            with st.expander(f"{title[:80]}..."):
                st.markdown(f"**生成日時**: {data['timestamp']}")
                st.markdown(data['summary'])

    if not st.session_state.papers and not st.session_state.summaries:
        st.info("まだデータがありません。「論文検索」タブから始めてください。")

# フッター
st.sidebar.markdown("---")
st.sidebar.markdown("### 📖 使い方")
st.sidebar.markdown("""
1. [Google AI Studio](https://makersuite.google.com/app/apikey)でAPI Keyを取得（無料）
2. 左のテキストボックスにAPI Keyを入力
3. 検索キーワードを入力して検索
4. 論文をクリックして要約生成
""")
st.sidebar.markdown("---")
st.sidebar.info("💡 セッション中のみデータを保持します。ブラウザを閉じるとリセットされます。")
