# PRなんJ打線ジェネレーター ⚾

GitHubのPull Requestデータから、なんJ風の野球打線を自動生成するスクリプトです。

## 特徴

- 🎯 **PRの変更量から打撃成績を算出**（打率、本塁打、OPSなど）
- ⚾ **なんJ風の一言キャッチフレーズを自動生成**（Claude CLI使用）
- 🔧 **リリースPRや統合マージを自動除外**（強すぎる選手を排除）
- 📊 **チーム統計やMVP情報も表示**
- 🤖 **Bot/AI作成PRも識別**

## インストール

```bash
# リポジトリをクローン
git clone <your-repo-url>
cd pr-nanj

# 必要なもの
# - Python 3.6以上
# - gh CLI (GitHub CLI)
# - claude CLI (オプション、キャッチフレーズ自動生成用)
```

## 使い方

### 1. PRデータを取得

```bash
# 直近100件のマージ済みPRを取得
gh pr list --state merged --limit 100 \
  --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \
  > prs.json
```

### 2. 打線を生成

```bash
# 基本的な使い方（リポジトリ名自動検出、マージPR除外、Claude自動生成）
python3 nanj.py prs.json

# ファイルに出力
python3 nanj.py prs.json --output lineup.md

# リポジトリ名を明示的に指定
python3 nanj.py prs.json --repo owner/reponame

# マージPR（リリース等）も含める
python3 nanj.py prs.json --include-merge-prs

# Claude CLI を使わない（デフォルトのキャッチフレーズ使用）
python3 nanj.py prs.json --no-claude
```

## オプション

| オプション | 説明 |
|-----------|------|
| `--repo`, `-r` | リポジトリ名を明示的に指定（省略時はPRデータから自動検出） |
| `--output`, `-o` | 出力ファイルパス（省略時は標準出力） |
| `--no-claude` | Claude CLIを使用せず、デフォルトのキャッチフレーズを使用 |
| `--include-merge-prs` | マージPR（リリース・integration等）を除外せずに含める |

## 出力例

```markdown
## 【悲報】your-repoリポジトリ、とんでもない打順を組んでしまうｗｗｗｗｗ

### ＝＝＝＝＝ なんJ民が選ぶ your-repo 最強打線 ＝＝＝＝＝

### 1番（二）「fix: エラーハンドリングを改善」
[PR-1234](https://github.com/owner/repo/pull/1234)
- 変更量 +15-8 ← これだけで仕事してて草
- 打率.318 出塁率.412
- **「23行で世界を変える男」**

### 4番（一）「feat: 新しいユーザー認証機能を追加」
[PR-1235](https://github.com/owner/repo/pull/1235)
- 変更量 +2500-150 ← ファッ！？
- 打率.342 本塁打52本 OPS1.123
- **「圧倒的破壊力、リポジトリの四番打者」**

...（中略）...

---

### 【解説】
なお、この打線で日本シリーズ制覇した模様ｗｗｗｗｗ
- 総PR数: **100本**
- チーム総変更行数: **15,432行**
- チーム打率: **.285**

彡(ﾟ)(ﾟ)「やっぱyour-repoって神だわ」
```

## マージPRの除外について

デフォルトでは、以下のPRが自動的に除外されます：

- `main`/`master`へのマージ（リリースPR）
- `develop`へのマージ（統合マージPR）

これらのPRは複数のPRの変更をまとめているため、変更量が異常に大きくなり、打線が強くなりすぎるためです。

除外されたくない場合は `--include-merge-prs` オプションを使用してください。

## PRデータ取得の詳細

### 年度別取得

```bash
# 2024年のPR
gh pr list --state merged --limit 1000 \
  --search "merged:2024-01-01..2024-12-31" \
  --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \
  > prs_2024.json
```

### 複数ファイルの結合

```bash
# 期間を分けて取得
gh pr list --state merged --limit 400 \
  --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \
  > prs_part1.json

gh pr list --state merged --limit 400 \
  --search "merged:<=2024-06-30" \
  --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \
  > prs_part2.json

# jqで結合
jq -s 'add' prs_part1.json prs_part2.json > prs_all.json

# 打線を生成
python3 nanj.py prs_all.json
```

## Claude CLIについて

キャッチフレーズの自動生成には[Claude CLI](https://github.com/anthropics/anthropic-tools)を使用します。

- Claude Maxプランの範囲内で動作（APIキー不要）
- 9人分のキャッチフレーズを並列生成（高速）
- PRの内容に合わせたなんJ風の自然な表現を生成

Claude CLIがインストールされていない、または使用したくない場合は `--no-claude` オプションを使用してください。

## 成績の計算式

### 重さ

```
PR重さ = 追加行数 + 削除行数 + (変更ファイル数 × 10)
```

### 打率

変更の効率性を表します。少ない変更で大きな影響を与えるほど高くなります。

- 超軽量PR（<20行）: .280〜.350
- 軽量PR（<100行）: .250〜.300
- 重量級PR（>5000行）: .180〜.220

### 本塁打

重さから算出されます（4番打者は補正あり）。

### OPS（出塁率 + 長打率）

総合的な打撃力を表します。

## トラブルシューティング

### JSONファイルが読み込めない

```bash
# JSONの妥当性をチェック
jq '.' prs.json > /dev/null && echo "JSONは有効です"
```

### APIレート制限に引っかかった

```bash
# レート制限の確認
gh api rate_limit
```

認証済み: 5000リクエスト/時
未認証: 60リクエスト/時

### リポジトリ名が自動検出されない

PRデータに `headRepository` と `headRepositoryOwner` が含まれているか確認してください。含まれていない場合は `--repo` オプションで明示的に指定してください。

## ライセンス

MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 貢献

プルリクエストを歓迎します！

## 参考

- [なんJ](https://ja.wikipedia.org/wiki/%E3%81%AA%E3%82%93J) - なんでも実況J板（野球板）
- [GitHub CLI](https://cli.github.com/)
- [Claude CLI](https://github.com/anthropics/anthropic-tools)
