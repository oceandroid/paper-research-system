# 論文研究システム

Google Scholarから論文を定期的にクローリングし、LLMで解析して可視化するシステムです。

## 主な機能

- Google Scholarから論文情報を自動クローリング
- SQLiteデータベースへの論文情報保存
- OpenAI APIを使った論文の自動解析・要約
- Streamlitによる直感的なWebUI
- ワードクラウドによる可視化
- 週次での自動実行スケジューラー

## プロジェクト構造

```
paper-research-system/
├── crawler/              # 論文クローリング
│   └── scholar_crawler.py
├── database/             # データベース管理
│   ├── models.py
│   ├── database.py
│   └── __init__.py
├── analyzer/             # 論文解析
│   └── llm_analyzer.py
├── scheduler/            # 定期実行
│   └── scheduler.py
├── frontend/             # UI
│   └── app.py
├── requirements.txt      # 依存パッケージ
└── README.md
```

## セットアップ

### 1. 依存パッケージのインストール

```bash
cd paper-research-system
pip install -r requirements.txt
```

### 2. OpenAI APIキーの設定

プロジェクトルートに `.env` ファイルを作成：

```bash
OPENAI_API_KEY=your-api-key-here
```

または、環境変数として設定：

```bash
export OPENAI_API_KEY="your-api-key-here"
```

## 使い方

### WebUIの起動

```bash
cd frontend
streamlit run app.py
```

ブラウザで `http://localhost:8501` が自動的に開きます。

### WebUIの機能

1. **ホーム**: ダッシュボードと最新の論文一覧
2. **論文検索・クローリング**: キーワードで論文を検索・取得
3. **データベース閲覧**: 保存済み論文の一覧・検索
4. **解析・可視化**: ワードクラウド、統計、一括解析
5. **設定**: APIキーの設定

### コマンドラインでの使用

#### 論文クローリング（1回のみ）

```bash
python scheduler/scheduler.py --mode once
```

#### 定期実行スケジューラーの起動

```bash
# 毎週月曜日 9:00 に実行
python scheduler/scheduler.py --mode schedule --day mon --hour 9 --minute 0
```

オプション:
- `--day`: 曜日（mon, tue, wed, thu, fri, sat, sun）
- `--hour`: 時刻（0-23）
- `--minute`: 分（0-59）

### クローリングの対象キーワード変更

[scheduler/scheduler.py](scheduler/scheduler.py:134-140) の `KEYWORDS` リストを編集：

```python
KEYWORDS = [
    "mass spectrometry",
    "proteomics",
    "metabolomics",
]
```

## データベース

SQLiteを使用しています。データベースファイル: `papers.db`

### テーブル構造

- **papers**: 論文情報
- **analyses**: 解析結果
- **crawl_logs**: クローリング履歴

## 開発

### 論文クローラーのテスト

```bash
python crawler/scholar_crawler.py
```

### データベースのテスト

```bash
python database/database.py
```

### LLM解析のテスト

```bash
python analyzer/llm_analyzer.py
```

## 注意事項

### Google Scholar API制限

- scholarly ライブラリはスクレイピングベースのため、大量の連続リクエストは避けてください
- クローリング間隔は2秒以上空けています
- 1回のクローリングで取得する論文数は10-20件程度を推奨

### OpenAI API使用料

- GPT-3.5-turboを使用しています
- 大量の論文を解析する場合、APIコストにご注意ください
- 解析は任意で実行可能です

## トラブルシューティング

### scholarly でエラーが発生する場合

Google Scholarのアクセス制限に引っかかっている可能性があります。
時間を空けて再試行してください。

### データベースエラー

データベースファイルを削除して再起動：

```bash
rm papers.db
```

### APIキーエラー

`.env` ファイルが正しく設定されているか確認してください。

## ライセンス

MIT License

## 作成者

論文研究システム開発チーム

