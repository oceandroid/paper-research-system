"""
PubMed APIから論文情報を取得するモジュール
Google Scholarがブロックされる場合の代替手段
"""
import time
import requests
from typing import List, Dict, Optional
from datetime import datetime
from xml.etree import ElementTree as ET


class PubMedCrawler:
    """PubMed APIから論文情報を取得するクラス"""

    def __init__(self, email: str = "your_email@example.com"):
        """
        Args:
            email: PubMed APIの利用規約に従い、メールアドレスを設定
        """
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.email = email

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
            # ステップ1: 検索してPubMed IDのリストを取得
            search_url = f"{self.base_url}esearch.fcgi"
            search_params = {
                'db': 'pubmed',
                'term': keyword,
                'retmax': max_results,
                'retmode': 'json',
                'email': self.email,
                'sort': 'relevance'
            }

            # 年指定がある場合
            if year_from:
                current_year = datetime.now().year
                search_params['datetype'] = 'pdat'
                search_params['mindate'] = f"{year_from}/01/01"
                search_params['maxdate'] = f"{current_year}/12/31"

            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()

            # PubMed IDリストを取得
            id_list = search_data.get('esearchresult', {}).get('idlist', [])

            if not id_list:
                print("論文が見つかりませんでした")
                return papers

            print(f"{len(id_list)}件の論文IDを取得しました")

            # ステップ2: 各論文の詳細情報を取得
            fetch_url = f"{self.base_url}efetch.fcgi"

            # 5件ずつ取得（API制限対策）
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

                # XMLをパース
                root = ET.fromstring(fetch_response.content)

                # 各論文の情報を抽出
                for article in root.findall('.//PubmedArticle'):
                    try:
                        paper_info = self._extract_paper_info(article, keyword)
                        papers.append(paper_info)
                    except Exception as e:
                        print(f"論文情報の抽出エラー: {e}")
                        continue

                # API制限を避けるため少し待機
                time.sleep(0.5)

            print(f"取得完了: {len(papers)}件の論文を取得しました")
            return papers

        except requests.exceptions.RequestException as e:
            print(f"PubMed API通信エラー: {e}")
            return papers
        except Exception as e:
            print(f"検索エラー: {e}")
            return papers

    def _extract_paper_info(self, article_xml, keyword: str) -> Dict:
        """XMLから論文情報を抽出"""
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

        # URL（PubMedのリンク）
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else 'N/A'

        # DOI
        doi_elem = article_xml.find('.//ArticleId[@IdType="doi"]')
        doi = doi_elem.text if doi_elem is not None else None

        paper_info = {
            'title': title,
            'authors': authors,
            'year': year,
            'abstract': abstract,
            'venue': venue,
            'url': url,
            'doi': doi,
            'pmid': pmid,
            'citations': 0,  # PubMedでは引用数は取得できない
            'crawled_at': datetime.now().isoformat(),
            'keyword': keyword,
            'source': 'PubMed'  # データソースを明示
        }

        return paper_info

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
        # PubMedのreldate パラメータを使用
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
                'reldate': days  # 直近n日間
            }

            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()

            id_list = search_data.get('esearchresult', {}).get('idlist', [])

            if not id_list:
                print(f"直近{days}日間の論文が見つかりませんでした")
                return papers

            # 詳細情報を取得
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
                except Exception as e:
                    print(f"論文情報の抽出エラー: {e}")
                    continue

            print(f"取得完了: {len(papers)}件の論文を取得しました")
            return papers

        except Exception as e:
            print(f"検索エラー: {e}")
            return papers


if __name__ == "__main__":
    # テスト実行
    crawler = PubMedCrawler(email="test@example.com")
    papers = crawler.search_papers("mass spectrometry proteomics", max_results=5, year_from=2024)

    print(f"\n取得した論文数: {len(papers)}")
    for i, paper in enumerate(papers, 1):
        print(f"\n--- 論文 {i} ---")
        print(f"タイトル: {paper['title']}")
        print(f"著者: {', '.join(paper['authors'][:3])}..." if len(paper['authors']) > 3 else ', '.join(paper['authors']))
        print(f"年: {paper['year']}")
        print(f"ジャーナル: {paper['venue']}")
        print(f"URL: {paper['url']}")
