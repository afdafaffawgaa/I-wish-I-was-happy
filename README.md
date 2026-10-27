# LARRY FiT 下館店｜混雑度の定期取得

下館駅近くの **LARRY FiT 下館店（茨城県筑西市乙863-2）** について、Google マップの「訪問数の多い時間帯」の**通常の混雑指数**および提供時のみ**ライブ混雑指数**を SerpApi の Google Maps Place Results API から取得するプロジェクトです。

> [!IMPORTANT]
> **初期状態では実データは未取得です。** SerpApi の API キーが必要です。Google が店舗の Popular Times を返さない場合は `unavailable` と記録し、混雑を捏造しません。Google公式Places APIには、同じグラフを取得できる公開フィールドがありません（2026年10月時点）。

## 使い始める手順（約5ステップ）

1. [GitHub](https://github.com/new) で**公開（Public）**リポジトリを新規作成し、このフォルダの**中身を丸ごと**アップロードします。サブフォルダとしてアップロードしないでください。
2. [SerpApi](https://serpapi.com/users/sign_up) に登録し、[API Key](https://serpapi.com/manage-api-key) を取得します。公式料金表では無料枠 **月250検索**（取得時点）。
3. GitHub リポジトリの **Settings → Secrets and variables → Actions → New repository secret** を開き、名前 `SERPAPI_API_KEY`、値に自分の API キーを登録します。**キーをソースコードに貼らないこと。**
4. 先に **Settings → Pages → Build and deployment → Source → GitHub Actions** を選びます。従来の「Deploy from a branch」は選ばないでください。GitHub Actions が更新のたびに直接公開します。
5. **Actions → LARRYFIT crowd collection and website → Run workflow → Run workflow** で初回実行します。「collect」と「deploy」の両ジョブが緑色になれば成功です。初回は Google マップの対象店舗を検索してから詳細を取得するため、通常2リクエスト、以降は場所識別子が保存されれば通常1リクエストです。URL は `https://＜ユーザー名＞.github.io/＜リポジトリ名＞/` の形です。

GitHub Pages のソースは **GitHub Actions** にしてください。Actions が `GITHUB_TOKEN` でコミットしただけでは GitHub Pages の branch-deploy は通常起動しないため、ワークフローに直接デプロイ手順を追加しています。

これで日本時間 **毎日 03:17、09:17、15:17、21:17** を目標に自動取得します。スケジュールは混雑などで遅延・取りこぼしがありえます。

## ブラウザー操作を一歩ずつ（PC推奨）

1. [GitHub 新しいリポジトリ](https://github.com/new) でリポジトリ名を `larryfit-crowd`、公開範囲を `Public` にする。README・gitignore・License は追加せず作成。
2. ZIP を解凍したら `larryfit-crowd-monitor` フォルダを**開き**、中に入っているファイル／フォルダをすべて選択して、GitHub の `uploading an existing file`（または `Add file → Upload files`）へドラッグ。**外側の `larryfit-crowd-monitor` フォルダをドラッグしてはいけません**。ZIP自体もアップロードしません。macOS で `.github` が見えなければ Finder で `⌘ + Shift + .` を押して表示。
3. `Commit changes` を押す。リポジトリの直下に `collector.py`、`index.html`、`data`、`.github/workflows/collect.yml` が存在することを確認。
4. [SerpApi に登録](https://serpapi.com/users/sign_up) → [APIキーの管理](https://serpapi.com/manage-api-key) で API key をコピー。
5. GitHubのリポジトリで `Settings → Secrets and variables → Actions → Secrets → New repository secret`。`Name` に `SERPAPI_API_KEY`、`Secret` にキーの値を入力して `Add secret`。コードやチャットにキーを公開しない。
6. **先に** `Settings → Pages → Build and deployment → Source → GitHub Actions` を選択する（`Deploy from a branch` ではない）。
7. `Actions → LARRYFIT crowd collection and website → Run workflow → Run workflow` を押して手動実行。実行履歴を開いて、`collect` と `deploy` がともに成功（緑）なら完了。
8. `Settings → Pages → Visit site`、または `https://＜GitHubユーザー名＞.github.io/larryfit-crowd/` を開く。サイトの「最新JSON」も確認する。

### エラーへの対処

- `SERPAPI_API_KEY is missing`：Secretの名前や登録先を確認。
- `not found in Google Maps search`：Google上の店名・住所の表記を確認。必要なら `SERPAPI_PLACE_ID` を追加する。
- `status: unavailable`：処理成功でも、Googleがその店舗の混雑データを返さなかったことを意味する。ゼロ人ではない。
- `Permission denied` / `403`（コミット時）：Actions の `GITHUB_TOKEN` に書き込み権限が許可されているか、リポジトリの権限設定を確認。
- `deploy` が失敗：Pagesの `Source` が `GitHub Actions` になっているかを確認。
- `Actions` にワークフローが出ない：`.github/workflows/collect.yml` がリポジトリ直下にあるかを確認。

## ChatGPTに分析させる

リポジトリを公開して、チャットで次の形式で送ってください。

> この LARRYFIT の混雑JSONを読んで、火曜日に一番空いている時間を分析して：`https://raw.githubusercontent.com/＜ユーザー名＞/＜リポジトリ名＞/main/data/latest.json`

最新グラフだけでなく、`data/history.jsonl` の URL も送れば、取得時のライブ混雑値の履歴がある範囲で分析できます。**ChatGPTが自動で定期実行するわけではなく GitHub Actions が実行します。**

## 主なファイル

- `collector.py`: SerpApi を呼び出して店舗照合・正規化・保存する。外部Pythonパッケージ不要。
- `.github/workflows/collect.yml`: 毎日4回のスケジュール、手動実行、GitHub Pagesの更新。
- `data/latest.json`: 最後の取得結果。24時間×7曜日の指数、欠損は `null`。
- `data/history.jsonl`: 取得時刻、取得成否、ライブ指数（提供時のみ）、その時刻の通常指数。
- `data/location.json`: 初回取得後に保存される店舗の Google マップ識別子。
- `index.html`: 曜日切り替え・棒グラフ・空いている候補を表示するページ。

## ローカルで試す

```bash
python -m unittest discover -s tests -v
export SERPAPI_API_KEY="取得したキー"
python collector.py
python -m http.server 8000
# http://localhost:8000/ を開く
```

対象の自動検索が失敗したときだけ、[Google マップの対象店舗](https://www.google.com/maps/search/?api=1&query=LARRY%20FiT%20%E4%B8%8B%E9%A4%A8%E5%BA%97) に対応する **Google Place ID** を調べて `SERPAPI_PLACE_ID` を GitHub Actions の Secret に追加できます。設定する場合も必ず店舗名・住所を照合し、LifeFit下館店などの別のジムを誤選択しないようにしています。

## 費用・制限

- 無料枠は SerpApi の [料金表](https://serpapi.com/pricing) を確認してください。1日4回なら通常 **月120〜124検索** 程度（初回検索の追加を除く）。ほかの用途で同じ API キーを使うなら共有枠に注意してください。
- 24時間連続で取得しているわけではないため、ライブ値は**取得時点のスナップショット**です。「今のリアルタイム」を保証しません。
- Google 側が Popular Times を提供しなければ取得できません。**データがない ≠ 客がいない**。数値は相対的な混雑指数で、人数の実数でも学生だけの混雑でもありません。
- GitHub の [スケジュール](https://docs.github.com/ja/actions/reference/workflows-and-actions/events-that-trigger-workflows) は遅延・失敗の可能性があり、公開リポジトリで60日以上非アクティブだと自動無効になる場合があります。
- 公開 GitHub Pages を利用すると、`data/latest.json` と取得履歴も第三者から閲覧できます。APIキーは**絶対に公開しない**でください。
- Google等のサービス規約とデータ利用条件もご確認ください。

## 取得間隔の変更

`.github/workflows/collect.yml` 内の `cron` を変更します。日本時間指定は `timezone: 'Asia/Tokyo'` です。例えば毎日1回午前6:17なら `17 6 * * *`。毎時取得にすると無料枠を超えるおそれがあります。
