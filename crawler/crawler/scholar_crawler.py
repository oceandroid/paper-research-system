"""
Google Scholarから論文情報をクローリングするモジュール
"""
import time
from typing import List, Dict, Optional
from scholarly import scholarly, ProxyGenerator
from datetime import datetime, timedelta


class ScholarCrawler:
    """Google Scholarから論文情報を取得するクラス"""

    def __init__(self):
        self.results = []

        # プロキシ設定を追加（Google Scholarのブロック対策）
        try:
            pg = ProxyGenerator()
            # FreeProxyを使用（無料）
            pg.FreeProxies()
            scholarly.use_proxy(pg)
            print("プロキシ設定完了")
        except Exception as e:
            print(f"プロキシ設定エラー（プロキシなしで続行）: {e}")

    def search_papers(
        self,
        keyword: str,
        max_results: int = 20,
        year_from: Optional[int] = None
    ) -> List[Dict]:
        """
        キーワードで論文を検索

        Args:
            keyword: 検索キーワード
            max_results: 取得する最大論文数
            year_from: 検索開始年（指定しない場合は全期間）

        Returns:
            論文情報のリスト
        """
        papers = []

        try:
            # 年指定がある場合はクエリに追加
            search_query = keyword
            if year_from:
                search_query = f"{keyword} after:{year_from}"

            # Google Scholarで検索
            search_results = scholarly.search_pubs(search_query)

            count = 0
            for result in search_results:
                if count >= max_results:
                    break

                try:
                    # 論文情報を抽出
                    paper_info = {
                        'title': result.get('bib', {}).get('title', 'N/A'),
                        'authors': result.get('bib', {}).get('author', []),
                        'year': result.get('bib', {}).get('pub_year', 'N/A'),
                        'abstract': result.get('bib', {}).get('abstract', 'N/A'),
                        'venue': result.get('bib', {}).get('venue', 'N/A'),
                        'url': result.get('pub_url', result.get('eprint_url', 'N/A')),
                        'citations': result.get('num_citations', 0),
                        'crawled_at': datetime.now().isoformat(),
                        'keyword': keyword
                    }

                    papers.append(paper_info)
                    count += 1

                    # API制限を避けるため少し待機
                    time.sleep(2)

                except Exception as e:
                    print(f"論文情報の抽出エラー: {e}")
                    continue

            print(f"取得完了: {len(papers)}件の論文を取得しました")
            return papers

        except Exception as e:
            print(f"検索エラー: {e}")
            return papers

    def get_recent_papers(
        self,
        keyword: str,
        days: int = 7,
        max_results: int = 20
    ) -> List[Dict]:
        """
        直近n日間の論文を取得

        Args:
            keyword: 検索キーワード
            days: 何日前からの論文を取得するか
            max_results: 取得する最大論文数

        Returns:
            論文情報のリスト
        """
        # 年のみの指定なので、現在の年から検索
        current_year = datetime.now().year
        target_date = datetime.now() - timedelta(days=days)

        # 年をまたいでいる場合は前年も含める
        year_from = target_date.year

        return self.search_papers(keyword, max_results, year_from)


if __name__ == "__main__":
    # テスト実行
    crawler = ScholarCrawler()
    papers = crawler.search_papers("mass spectrometry", max_results=5, year_from=2024)

    print(f"\n取得した論文数: {len(papers)}")
    for i, paper in enumerate(papers, 1):
        print(f"\n--- 論文 {i} ---")
        print(f"タイトル: {paper['title']}")
        print(f"著者: {', '.join(paper['authors']) if isinstance(paper['authors'], list) else paper['authors']}")
        print(f"年: {paper['year']}")
        print(f"引用数: {paper['citations']}")
