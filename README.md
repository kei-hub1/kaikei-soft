# 論点ノート（kaikei-soft）

税理士事務所向けの、**顧問先ごとの検討論点を蓄積・検索するローカルアプリ**です。

案件で検討した税務論点と結論・根拠・翌年以降の留意点を記録しておき、翌年の申告時や別の顧問先の類似案件で引き当てられるようにします。

- インストール不要・依存ライブラリなし（Python 標準ライブラリのみ）
- データは PC 内の SQLite ファイル 1 つに保存（外部送信なし）
- 日本語全文検索（SQLite FTS5 / trigram）
- ブラウザで操作（Edge / Chrome など）

## 必要なもの

- Python 3.8 以上（Windows は [python.org](https://www.python.org/downloads/windows/) からインストール。「Add python.exe to PATH」にチェック）

## 起動方法

- Windows: `start.bat` をダブルクリック
- macOS / Linux: `./start.sh`
- 直接: `python -m ronten`

自動でブラウザが開き `http://127.0.0.1:8765/` が表示されます。終了はコンソールで `Ctrl+C`。

```
python -m ronten --help
  --db PATH      データファイル（既定: data/ronten.db。環境変数 RONTEN_DB でも指定可）
  --port N       ポート番号（既定: 8765）
  --host ADDR    待受アドレス（既定: 127.0.0.1 = このPCのみ）
  --no-browser   起動時にブラウザを開かない
```

動作確認用のサンプルデータ（架空）を入れるには:

```
python scripts/seed_sample.py --db data/sample.db
python -m ronten --db data/sample.db
```

## できること

### 顧問先
名称・かな・コード・区分（法人/個人）・決算月・業種・担当者・メモを登録。顧問先ページには論点が事業年度ごとに並び、**要フォロー**（検討中・要再検討・翌年以降の留意点あり）が上部にまとまります。

### 論点
1 件の論点に次を記録します。

| 項目 | 内容 |
|---|---|
| 論点名 / 税目 / 事業年度 / ステータス | 検討中・結論済・要再検討・保留 |
| 事実関係・前提 | 取引内容、金額、時期、契約関係など |
| 論点 | 何が問題か |
| 検討内容 | 考えられる取扱いと根拠・リスク |
| 結論 | 採用した取扱いと理由 |
| 根拠 | 条文・通達・判例・質疑応答事例など |
| 翌年以降の留意点 | 翌期の申告で確認すべきこと。要フォローとして表示される |
| 担当者 / 確認者 / 結論日 / タグ | |

- **更新履歴**: 更新するたびに変更前の内容を保存し、差分を表示
- **類似論点**: 論点名・タグ・論点欄のキーワードから、他の顧問先を含む類似論点を自動表示
- **翌年分として複製**: 前年の論点を引き継いで新しい事業年度の論点を作成（留意点は論点欄に「前年からの引継ぎ」として転記）
- **印刷**: ブラウザの印刷でメモとして出力

### 検索
キーワード（顧問先名・論点名・本文・タグ・税目・年度を横断）＋ 顧問先 / 税目 / ステータス / 事業年度 / タグ / 担当者 / 要フォローのみ で絞り込み。複数語はスペース区切りで AND 検索。ヒット箇所をハイライト表示します。`/` キーで検索欄にフォーカス。

### バックアップ
設定ページから JSON（復元用）/ CSV（Excel 用）を書き出せます。データファイル `data/ronten.db` をコピーするだけでもバックアップになります（アプリ終了後にコピーしてください）。JSON は追加取り込みも可能です。

## 事務所内で共有する場合

既定では自PCからのみアクセスできます。事務所内の他の PC から使う場合は `--host 0.0.0.0` で起動し、`http://<そのPCのIPアドレス>:8765/` を開きます。認証機能はないため、信頼できる LAN 内でのみ使ってください。

## 開発

```
python -m unittest discover -s tests -v
```

構成:

```
ronten/
  db.py         SQLite データ層（スキーマ・検索・履歴・エクスポート）
  server.py     内蔵 HTTP サーバー / JSON API
  __main__.py   起動 CLI
  static/       画面（index.html, app.js, style.css）
scripts/seed_sample.py  サンプルデータ投入
tests/          ユニットテスト
```

API の概要: `GET/POST /api/clients`, `GET/PUT/DELETE /api/clients/{id}`, `GET /api/clients/{id}/issues`, `GET/POST /api/issues`, `GET/PUT/DELETE /api/issues/{id}`, `GET /api/issues/{id}/similar`, `GET /api/issues/{id}/revisions`, `GET /api/meta`, `GET /api/export.json`, `GET /api/export.csv`, `POST /api/import`
