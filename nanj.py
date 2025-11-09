#!/usr/bin/env python3
"""
PRなんJ打線生成スクリプト
GitHubリポジトリのPRデータから、なんJ風の野球打線を作成する
"""

import json
import sys
import argparse
import os
import subprocess
from typing import List, Dict, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


class NanJLineup:
    """なんJ風PR打線を生成するクラス"""

    def __init__(self, repo: str = "username/reponame", use_claude: bool = True, include_merge_prs: bool = False):
        self.repo = repo
        self.all_prs = []
        self.sorted_prs = []
        self.use_claude = use_claude
        self.include_merge_prs = include_merge_prs
        self.catchphrases = {}  # position -> catchphrase
        self.categories = {
            'small_fixes': [],
            'bug_fixes': [],
            'features': [],
            'releases': [],
            'bot_prs': [],
            'devin_prs': [],
            'huge_prs': [],
            'merge_prs': []
        }

    def is_merge_pr(self, pr: Dict[str, Any]) -> bool:
        """マージPR（リリース、integration等）かどうか判定"""
        base_ref = pr.get('baseRefName', '')
        head_ref = pr.get('headRefName', '')

        # main/master へのマージ（リリースPR）
        if base_ref in ['main', 'master', 'develop']:
            return True

        return False

    def extract_repo_from_prs(self, prs: List[Dict[str, Any]]) -> Optional[str]:
        """PRデータからリポジトリ名を抽出"""
        for pr in prs:
            # headRepository と headRepositoryOwner から抽出
            head_repo = pr.get('headRepository')
            head_owner = pr.get('headRepositoryOwner')

            if head_repo and head_owner:
                repo_name = head_repo.get('name')
                owner_login = head_owner.get('login')

                if repo_name and owner_login:
                    return f"{owner_login}/{repo_name}"

            # 旧形式: headRepository.owner.login も試す
            if head_repo and isinstance(head_repo, dict):
                repo_name = head_repo.get('name')
                owner = head_repo.get('owner', {})
                owner_login = owner.get('login') if isinstance(owner, dict) else None

                if repo_name and owner_login:
                    return f"{owner_login}/{repo_name}"

        return None

    def load_prs_from_file(self, filepath: str) -> None:
        """JSONファイルからPRデータを読み込む"""
        print(f"📊 {filepath}からPRデータを読み込み中...", file=sys.stderr)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                prs = json.load(f)

            # リストでない場合はリストに変換
            if not isinstance(prs, list):
                prs = [prs]

            # マージ済みのみフィルタ（mergedAtがあるものだけ）
            merged_prs = [pr for pr in prs if pr.get('mergedAt')]

            # マージPRのフィルタリング
            if not self.include_merge_prs:
                filtered_count = 0
                filtered_prs = []
                for pr in merged_prs:
                    if self.is_merge_pr(pr):
                        filtered_count += 1
                    else:
                        filtered_prs.append(pr)
                self.all_prs = filtered_prs

                if filtered_count > 0:
                    print(f"🔧 マージPR（リリース・integration等）を {filtered_count} 件除外しました", file=sys.stderr)
            else:
                self.all_prs = merged_prs

            print(f"✨ 合計 {len(self.all_prs)} 件のPRを読み込み完了！", file=sys.stderr)

            # リポジトリ名が未設定の場合、PRデータから抽出
            if self.repo == "username/reponame":
                extracted_repo = self.extract_repo_from_prs(self.all_prs)
                if extracted_repo:
                    self.repo = extracted_repo
                    print(f"🔍 リポジトリ名を自動検出: {self.repo}", file=sys.stderr)
                else:
                    print(f"⚠️  リポジトリ名を自動検出できませんでした。デフォルト '{self.repo}' を使用します。", file=sys.stderr)
                    print(f"   ヒント: gh pr list に --json オプションで headRepository,headRepositoryOwner を含めてください", file=sys.stderr)

        except FileNotFoundError:
            print(f"❌ エラー: ファイル '{filepath}' が見つかりません", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ エラー: JSONの解析に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"❌ エラー: ファイル読み込み中にエラーが発生しました: {e}", file=sys.stderr)
            sys.exit(1)

    def calculate_weights(self) -> None:
        """PRの重さを計算"""
        for pr in self.all_prs:
            # 重さ = 追加行 + 削除行 + (ファイル数 × 10)
            pr['weight'] = (
                pr.get('additions', 0) +
                pr.get('deletions', 0) +
                (pr.get('changedFiles', 0) * 10)
            )

        # 重さでソート
        self.sorted_prs = sorted(self.all_prs, key=lambda x: x['weight'], reverse=True)

    def categorize_prs(self) -> None:
        """PRをカテゴリ分け"""
        for pr in self.sorted_prs:
            title = pr['title'].lower()
            author = pr.get('author', {}).get('login', '')
            is_bot = pr.get('author', {}).get('is_bot', False)

            # リリース系
            if 'release' in title or '[prod]' in title or '[stg]' in title:
                self.categories['releases'].append(pr)

            # Devin AI
            if 'devin' in author:
                self.categories['devin_prs'].append(pr)
            elif is_bot:
                self.categories['bot_prs'].append(pr)

            # バグ修正
            if 'fix' in title or 'bug' in title or 'error' in title:
                self.categories['bug_fixes'].append(pr)

            # 機能追加
            if 'feat' in title or 'feature' in title:
                self.categories['features'].append(pr)

            # マージ・差分吸収
            if '差分' in title or 'merge' in title.lower():
                self.categories['merge_prs'].append(pr)

            # 小さい修正
            if pr['weight'] < 100:
                self.categories['small_fixes'].append(pr)

            # 巨大PR
            if pr['weight'] > 10000:
                self.categories['huge_prs'].append(pr)

    def find_pr_by_criteria(self, condition, fallback_index: int = 50) -> Dict[str, Any]:
        """条件に合うPRを探す"""
        for pr in self.sorted_prs:
            if condition(pr):
                return pr
        return self.sorted_prs[min(fallback_index, len(self.sorted_prs) - 1)]

    def format_pr_link(self, pr: Dict[str, Any]) -> str:
        """PR番号とURLをマークダウン形式でフォーマット"""
        return f"[PR-{pr['number']}](https://github.com/{self.repo}/pull/{pr['number']})"

    def generate_single_catchphrase(self, position: int, pr: Dict[str, Any]) -> str:
        """Claude CLIを使って1人分のキャッチフレーズを生成"""
        position_desc = {
            1: "1番・二塁手（俊足巧打、出塁率が高い）",
            2: "2番・遊撃手（バント・守備の職人）",
            3: "3番・右翼手（中距離砲、チャンスに強い）",
            4: "4番・一塁手（最強の破壊力、本塁打王）",
            5: "5番・左翼手（4番に次ぐパワー）",
            6: "6番・三塁手（つなぎの役割、得点圏打率が高い）",
            7: "7番・捕手（守備重視、地味だが堅実）",
            8: "8番・中堅手（下位打線、期待値低め）",
            9: "9番・投手（最弱打者、でも投手だから...）"
        }

        total_lines = pr.get('additions', 0) + pr.get('deletions', 0)

        prompt = f"""以下のPR情報から、野球のなんJ風の一言キャッチフレーズを生成してください。

【PR情報】
- ポジション: {position_desc.get(position, f'{position}番')}
- PRタイトル: {pr['title']}
- 追加行数: {pr.get('additions', 0)}行
- 削除行数: {pr.get('deletions', 0)}行
- 合計変更: {total_lines}行
- 変更ファイル数: {pr.get('changedFiles', 0)}ファイル

【生成条件】
1. なんJ（2ちゃんねる野球板）風の言い回しで
2. PRの内容とポジションの特性を反映
3. 15文字以内で簡潔に
4. 「〜男」「〜の鬼」「〜やんけ」等のなんJ用語を使う
5. キャッチフレーズのみ出力（説明不要）

【出力例】
エラーを見たら黙ってない男
{total_lines}行で世界を変える男
圧倒的破壊力、リポジトリの四番打者

【出力】
"""

        try:
            result = subprocess.run(
                ['claude', '--print', '--output-format', 'text'],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                print(f"⚠️  {position}番のClaude呼び出しエラー: {result.stderr}", file=sys.stderr)
                return f"PR-{pr['number']}の選手"

            catchphrase = result.stdout.strip()
            # 余計な装飾を削除
            catchphrase = catchphrase.replace('**「', '').replace('」**', '')
            catchphrase = catchphrase.replace('「', '').replace('」', '')
            catchphrase = catchphrase.replace('**', '')
            catchphrase = catchphrase.strip('"\'')

            # 空の場合はデフォルト
            if not catchphrase:
                return f"PR-{pr['number']}の選手"

            return catchphrase
        except subprocess.TimeoutExpired:
            print(f"⚠️  {position}番のキャッチフレーズ生成がタイムアウト", file=sys.stderr)
            return f"PR-{pr['number']}の選手"
        except Exception as e:
            print(f"⚠️  {position}番のキャッチフレーズ生成に失敗: {e}", file=sys.stderr)
            return f"PR-{pr['number']}の選手"

    def generate_all_catchphrases(self, lineup_data: Dict[int, Dict[str, Any]]) -> None:
        """9人分のキャッチフレーズを並列生成"""
        print("🤖 Claude CLIでキャッチフレーズを並列生成中...", file=sys.stderr)

        with ThreadPoolExecutor(max_workers=9) as executor:
            future_to_position = {
                executor.submit(self.generate_single_catchphrase, position, pr): position
                for position, pr in lineup_data.items()
            }

            for future in as_completed(future_to_position):
                position = future_to_position[future]
                try:
                    catchphrase = future.result()
                    self.catchphrases[position] = catchphrase
                    print(f"  ✓ {position}番: {catchphrase}", file=sys.stderr)
                except Exception as e:
                    print(f"  ✗ {position}番: 生成失敗 - {e}", file=sys.stderr)
                    self.catchphrases[position] = f"PR選手{position}番"

    def calculate_stats(self, pr: Dict[str, Any], position: int = 5) -> Dict[str, Any]:
        """PRデータから野球の成績を算出"""
        additions = pr.get('additions', 0)
        deletions = pr.get('deletions', 0)
        files = pr.get('changedFiles', 0)
        weight = pr.get('weight', 0)

        # 打率：変更の効率性 (少ない変更で大きな影響を与えるほど高い)
        # より現実的な打率に調整
        if weight == 0:
            # 変更量0は投手らしく低打率
            batting_avg = 0.089
        elif weight < 20:
            # 超軽量PRは効率良いので高打率（.280〜.350）
            batting_avg = 0.280 + min(0.070, 20 / max(weight, 1) * 0.003)
        elif weight < 100:
            # 軽量PR（.250〜.300）
            batting_avg = 0.250 + min(0.050, 50 / weight * 0.02)
        elif weight < 500:
            # 中量級PR（.230〜.280）
            batting_avg = 0.230 + min(0.050, 100 / weight * 0.1)
        elif weight < 5000:
            # 重量級PR（.200〜.250）
            batting_avg = 0.200 + min(0.050, 500 / weight * 0.1)
        else:
            # 超重量級PR（.180〜.220）
            batting_avg = 0.180 + min(0.040, 1000 / weight * 0.1)

        # ポジション補正（もっと控えめに）
        position_bonus = {
            1: 0.020,  # 1番はアベレージヒッター
            2: 0.010,  # 2番は小技
            3: 0.015,  # 3番は中距離
            4: 0.030,  # 4番は打点王
            5: -0.010, # 5番は少し下がる
            6: -0.015, # 6番以降は下がり気味
            7: -0.020,
            8: -0.025,
            9: -0.050  # 投手は大幅に下がる
        }
        batting_avg += position_bonus.get(position, 0)
        batting_avg = max(0.089, min(0.380, batting_avg))  # 打率の範囲を制限

        # 出塁率：打率より少し高め（実際の野球と同じ）
        obp = min(0.450, batting_avg + 0.040 + (files * 0.0005))

        # 本塁打：重さから算出（より現実的に）
        if position == 4:  # 4番打者補正
            home_runs = min(52, int(weight / 500) + 20)
        elif position in [3, 5]:  # 中軸
            home_runs = min(38, int(weight / 700))
        else:
            home_runs = max(0, int(weight / 1000))

        # 守備率：バグ修正や差分吸収なら高め
        title_lower = pr['title'].lower()
        if 'fix' in title_lower or 'bug' in title_lower:
            fielding = 0.975 + min(0.020, 10 / max(files, 1) * 0.005)
        elif '差分' in pr['title'] or 'merge' in title_lower:
            fielding = 0.980 + min(0.015, 5 / max(files, 1) * 0.005)
        else:
            fielding = 0.950 + min(0.030, files * 0.0003)

        # 長打率：大きな変更ほど高い
        slugging_base = batting_avg + (weight / 15000) * 0.3
        slugging = min(0.650, slugging_base)

        # OPS = 出塁率 + 長打率
        ops = obp + slugging

        # 得点圏打率：通常打率の変動版
        clutch_avg = batting_avg + (0.020 if 'feat' in title_lower else -0.010)
        clutch_avg = max(0.089, clutch_avg)

        # 防御率（投手用）：小さいほど良い、ただし変更量0なら悪い
        if weight == 0:
            era = 5.42  # 変更量0は投手としてもダメ
        else:
            era = max(2.50, 7.00 - (min(weight, 1500) / 300))

        return {
            'batting_avg': round(batting_avg, 3),
            'obp': round(obp, 3),
            'home_runs': home_runs,
            'fielding': round(fielding, 3),
            'slugging': round(slugging, 3),
            'ops': round(ops, 3),
            'clutch_avg': round(clutch_avg, 3),
            'era': round(era, 2)
        }

    def prepare_lineup_data(self) -> Dict[int, Dict[str, Any]]:
        """打順を決定し、PR情報を返す"""
        lineup = {}

        # 1番: 軽いけど仕事するPR
        lineup[1] = self.find_pr_by_criteria(
            lambda pr: pr['weight'] < 20 and 'fix' in pr['title'].lower(),
            fallback_index=-10
        )

        # 2番: バグ修正職人
        lineup[2] = next(
            (pr for pr in self.categories['bug_fixes'] if pr['weight'] < 500),
            self.categories['bug_fixes'][0] if self.categories['bug_fixes']
            else self.sorted_prs[min(100, len(self.sorted_prs) - 1)]
        )

        # 3番: UI系や大型機能
        lineup[3] = self.find_pr_by_criteria(
            lambda pr: '直感' in pr['title'] or 'ui' in pr['title'].lower(),
            fallback_index=5
        )

        # 4番: 最大のPR
        lineup[4] = self.sorted_prs[0]

        # 5番: 2番目に大きいPR
        lineup[5] = self.sorted_prs[1] if len(self.sorted_prs) > 1 else self.sorted_prs[0]

        # 6番: マージ職人
        if self.categories['merge_prs']:
            lineup[6] = self.categories['merge_prs'][0]
        else:
            lineup[6] = self.sorted_prs[10] if len(self.sorted_prs) > 10 else self.sorted_prs[0]

        # 7番: 地味な改善
        lineup[7] = self.find_pr_by_criteria(
            lambda pr: ('update' in pr['title'].lower() or 'improve' in pr['title'].lower())
                      and 50 <= self.sorted_prs.index(pr) < 150,
            fallback_index=75
        )

        # 8番: Bot枠
        if self.categories['devin_prs']:
            lineup[8] = self.categories['devin_prs'][0]
        elif self.categories['bot_prs']:
            lineup[8] = self.categories['bot_prs'][0]
        else:
            lineup[8] = self.sorted_prs[-5] if len(self.sorted_prs) > 5 else self.sorted_prs[0]

        # 9番: 最弱PR
        lineup[9] = self.sorted_prs[-1]

        return lineup

    def generate_lineup(self) -> str:
        """なんJ風打線を生成"""
        # 打順を決定
        lineup_data = self.prepare_lineup_data()

        # Claude CLIでキャッチフレーズを生成
        if self.use_claude:
            self.generate_all_catchphrases(lineup_data)

        output = []
        output.append("## 【悲報】{}リポジトリ、とんでもない打順を組んでしまうｗｗｗｗｗ".format(
            self.repo.split('/')[-1]
        ))
        output.append("\n### ＝＝＝＝＝ なんJ民が選ぶ {} 最強打線 ＝＝＝＝＝\n".format(
            self.repo.split('/')[-1]
        ))

        # 1番: 軽いけど仕事するPR
        one_liner = lineup_data[1]
        stats_1 = self.calculate_stats(one_liner, position=1)
        total_lines = one_liner.get('additions', 0) + one_liner.get('deletions', 0)
        catchphrase_1 = self.catchphrases.get(1, f"{total_lines}行で世界を変える男")
        output.append(f"### 1番（二）「{one_liner['title'][:40]}」")
        output.append(self.format_pr_link(one_liner))
        output.append(f"- 変更量 +{one_liner.get('additions', 0)}-{one_liner.get('deletions', 0)} ← これだけで仕事してて草")
        output.append(f"- 打率{stats_1['batting_avg']:.3f} 出塁率{stats_1['obp']:.3f}")
        output.append(f"- **「{catchphrase_1}」**\n")

        # 2番: バグ修正職人
        craftsman = lineup_data[2]
        stats_2 = self.calculate_stats(craftsman, position=2)
        catchphrase_2 = self.catchphrases.get(2, "エラーを見たら黙ってない男")
        output.append(f"### 2番（遊）「{craftsman['title'][:40]}」")
        output.append(self.format_pr_link(craftsman))
        output.append("- エラー処理の鬼")
        output.append(f"- 打率{stats_2['batting_avg']:.3f} 守備率{stats_2['fielding']:.3f}")
        output.append(f"- **「{catchphrase_2}」**\n")

        # 3番: UI系や大型機能
        ui_pr = lineup_data[3]
        stats_3 = self.calculate_stats(ui_pr, position=3)
        catchphrase_3 = self.catchphrases.get(3, "チャンスに強い中距離砲")
        output.append(f"### 3番（右）「{ui_pr['title'][:40]}」")
        output.append(self.format_pr_link(ui_pr))
        output.append(f"- 変更量 +{ui_pr.get('additions', 0)}-{ui_pr.get('deletions', 0)} files:{ui_pr.get('changedFiles', 0)}")
        output.append(f"- 打率{stats_3['batting_avg']:.3f} 長打率{stats_3['slugging']:.3f}")
        output.append(f"- **「{catchphrase_3}」**\n")

        # 4番: 最大のPR
        cleanup_pr = lineup_data[4]
        stats_4 = self.calculate_stats(cleanup_pr, position=4)
        catchphrase_4 = self.catchphrases.get(4, "圧倒的破壊力、リポジトリの四番打者")
        output.append(f"### 4番（一）「{cleanup_pr['title'][:40]}」")
        output.append(self.format_pr_link(cleanup_pr))
        output.append(f"- 変更量 +{cleanup_pr.get('additions', 0)}-{cleanup_pr.get('deletions', 0)} ← ファッ！？")
        output.append(f"- 打率{stats_4['batting_avg']:.3f} 本塁打{stats_4['home_runs']}本 OPS{stats_4['ops']:.3f}")
        output.append(f"- **「{catchphrase_4}」**\n")

        # 5番: 2番目に大きいPR
        power_pr = lineup_data[5]
        stats_5 = self.calculate_stats(power_pr, position=5)
        catchphrase_5 = self.catchphrases.get(5, "四番の後ろを任せられる男")
        output.append(f"### 5番（左）「{power_pr['title'][:40]}」")
        output.append(self.format_pr_link(power_pr))
        output.append(f"- 変更 {power_pr.get('changedFiles', 0)}ファイル ← 暴れすぎやろ...")
        output.append(f"- 打率{stats_5['batting_avg']:.3f} 本塁打{stats_5['home_runs']}本")
        output.append(f"- **「{catchphrase_5}」**\n")

        # 6番: マージ職人
        merge_pr = lineup_data[6]
        stats_6 = self.calculate_stats(merge_pr, position=6)
        catchphrase_6 = self.catchphrases.get(6, "つなぐ野球の申し子")
        output.append(f"### 6番（三）「{merge_pr['title'][:40]}」")
        output.append(self.format_pr_link(merge_pr))
        output.append("- コンフリクト解決数∞ ← 縁の下の力持ち")
        output.append(f"- 打率{stats_6['batting_avg']:.3f} 得点圏打率{stats_6['clutch_avg']:.3f}")
        output.append(f"- **「{catchphrase_6}」**\n")

        # 7番: 地味な改善
        minor_pr = lineup_data[7]
        stats_7 = self.calculate_stats(minor_pr, position=7)
        catchphrase_7 = self.catchphrases.get(7, "地味だが堅実な仕事人")
        output.append(f"### 7番（捕）「{minor_pr['title'][:40]}」")
        output.append(self.format_pr_link(minor_pr))
        output.append(f"- 変更量 +{minor_pr.get('additions', 0)}-{minor_pr.get('deletions', 0)}")
        output.append(f"- 打率{stats_7['batting_avg']:.3f} 守備の要")
        output.append(f"- **「{catchphrase_7}」**\n")

        # 8番: Bot枠
        bot_pr = lineup_data[8]
        stats_8 = self.calculate_stats(bot_pr, position=8)
        catchphrase_8 = self.catchphrases.get(8, "人間じゃないのに頑張ってる")
        output.append(f"### 8番（中）「{bot_pr['title'][:40]}」")
        output.append(self.format_pr_link(bot_pr))
        author_name = bot_pr.get('author', {}).get('login', 'unknown')
        if bot_pr.get('author', {}).get('is_bot', False):
            output.append(f"- 作者: {author_name} ← AIやんけ！")
        else:
            output.append(f"- 作者: {author_name}")
        output.append(f"- 打率{stats_8['batting_avg']:.3f}")
        output.append(f"- **「{catchphrase_8}」**\n")

        # 9番: 最弱PR
        weakest = lineup_data[9]
        stats_9 = self.calculate_stats(weakest, position=9)
        catchphrase_9 = self.catchphrases.get(9, "でも投手だから...")
        output.append(f"### 9番（投）「{weakest['title'][:40]}」")
        output.append(self.format_pr_link(weakest))
        output.append(f"- 変更量 +{weakest.get('additions', 0)}-{weakest.get('deletions', 0)} ← しょぼすぎて泣いた")
        output.append(f"- 打率{stats_9['batting_avg']:.3f} 防御率{stats_9['era']:.2f}")
        output.append(f"- **「{catchphrase_9}」**\n")

        return "\n".join(output)

    def generate_stats(self) -> str:
        """統計情報を生成"""
        output = []

        # 基本統計
        output.append("---\n")
        output.append("### 【解説】")
        output.append("なお、この打線で日本シリーズ制覇した模様ｗｗｗｗｗ")
        output.append(f"- 総PR数: **{len(self.sorted_prs)}本**")
        total_changes = sum(pr.get('additions', 0) + pr.get('deletions', 0) for pr in self.sorted_prs)
        output.append(f"- チーム総変更行数: **{total_changes:,}行**")

        # チーム打率（全PRの打率を計算）
        avg_stats = [self.calculate_stats(pr)['batting_avg'] for pr in self.sorted_prs[:30]]
        team_avg = sum(avg_stats) / len(avg_stats) if avg_stats else 0.250
        output.append(f"- チーム打率: **{team_avg:.3f}**")
        output.append("\n彡(ﾟ)(ﾟ)「やっぱ{}って神だわ」".format(self.repo.split('/')[-1]))

        # 作者統計
        author_stats = {}
        for pr in self.sorted_prs:
            author = pr.get('author', {}).get('login', 'unknown')
            if author not in author_stats:
                author_stats[author] = {'count': 0, 'total_weight': 0}
            author_stats[author]['count'] += 1
            author_stats[author]['total_weight'] += pr['weight']

        sorted_authors = sorted(author_stats.items(), key=lambda x: x[1]['total_weight'], reverse=True)

        if sorted_authors:
            output.append("\n---\n")
            output.append("### 【速報】今シーズンMVP")
            mvp = sorted_authors[0]
            output.append(f"- **{mvp[0]}**: {mvp[1]['count']}本, 総重量{mvp[1]['total_weight']:,}")
            output.append("- 彡(ﾟ)(ﾟ)「化け物かな？」")

        # Bot統計
        if self.categories['devin_prs'] or self.categories['bot_prs']:
            output.append("\n### 【朗報】AI・Bot勢の活躍")
            if self.categories['devin_prs']:
                output.append(f"- Devin AI: {len(self.categories['devin_prs'])}本")
            if self.categories['bot_prs']:
                output.append(f"- その他Bot: {len(self.categories['bot_prs'])}本")
            output.append("- 彡(^)(^)「人間いらんやん」")

        # ベンチ入り
        output.append("\n---\n")
        output.append("### ベンチ入り選手（次点）")
        output.append("控えの有望株たち：")

        # なんJ語のバリエーション
        nanj_templates = [
            "破壊力{weight:,}やんけ",
            "パワー{weight:,}で草",
            "{weight:,}行、これもうレギュラーやろ",
            "実力値{weight:,}、期待の若手や",
            "{weight:,}の仕事量、ベンチ温めとる場合か？",
            "変更量{weight:,}で二軍落ちは草",
            "{weight:,}行も弄って控えとか贅沢すぎやろ",
            "ポテンシャル{weight:,}、いつでも使える便利屋や",
        ]

        for i, pr in enumerate(self.sorted_prs[20:25], 1):
            if i > len(self.sorted_prs[20:]):
                break
            # バリエーションから選択（PRのインデックスベースで固定）
            template = nanj_templates[(20 + i - 1) % len(nanj_templates)]
            comment = template.format(weight=pr['weight'])
            output.append(f"- {self.format_pr_link(pr)}: {pr['title'][:40]}... ← {comment}")

        return "\n".join(output)

    def run(self, input_file: str = None) -> str:
        """メイン実行"""
        if input_file:
            self.load_prs_from_file(input_file)
        else:
            print("❌ エラー: 入力ファイルを指定してください", file=sys.stderr)
            sys.exit(1)

        self.calculate_weights()
        self.categorize_prs()

        result = []
        result.append(self.generate_lineup())
        result.append(self.generate_stats())

        return "\n".join(result)


def main():
    """メインエントリーポイント"""
    parser = argparse.ArgumentParser(
        description='GitHubのPRデータからなんJ風野球打線を生成する',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
╔════════════════════════════════════════════════════════════════════════════════╗
║                     PRなんJ打線生成スクリプト 使用方法                          ║
╚════════════════════════════════════════════════════════════════════════════════╝

【必要要件】
  • Python 3.6以上
  • gh CLI（GitHubからPRデータを取得する場合）
  • jq（複数のJSONファイルを結合する場合、オプション）

【使い方】

  ▼ 基本的な使い方
    python3 nanj.py prs_latest.json

  ▼ ファイルに出力する場合
    python3 nanj.py prs_latest.json --output lineup.md

  ▼ リポジトリ名を指定する場合（表示用）
    python3 nanj.py prs_latest.json --repo yourorg/yourrepo

【PRデータの取得方法】

  事前にgh CLIを使用してPRデータをJSONファイルに保存してください。

  ▼ 基本形式:
    gh pr list --repo <owner/repo> --state merged \\
      --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName

  【重要】
  • headRepository,headRepositoryOwner を含めることで、--repo オプションが不要になります
  • baseRefName,headRefName を含めることで、マージPR（リリース等）を自動除外できます

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 直近のPR取得

  # 直近100件のマージ済みPRを取得
  gh pr list --state merged --limit 100 \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_latest_100.json

  # 直近500件
  gh pr list --state merged --limit 500 \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_latest_500.json

  # 直近1000件（上限に注意）
  gh pr list --state merged --limit 1000 \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_latest_1000.json

■ 年度別のPR取得

  # 2025年のPR
  gh pr list --state merged --limit 1000 \\
    --search "merged:2025-01-01..2025-12-31" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_2025.json

  # 2024年のPR
  gh pr list --state merged --limit 1000 \\
    --search "merged:2024-01-01..2024-12-31" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_2024.json

■ 四半期別のPR取得

  # 2024年Q4（10-12月）
  gh pr list --state merged --limit 500 \\
    --search "merged:2024-10-01..2024-12-31" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_2024_q4.json

  # 2024年Q3（7-9月）
  gh pr list --state merged --limit 500 \\
    --search "merged:2024-07-01..2024-09-30" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_2024_q3.json

  # 2024年Q2（4-6月）
  gh pr list --state merged --limit 500 \\
    --search "merged:2024-04-01..2024-06-30" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_2024_q2.json

  # 2024年Q1（1-3月）
  gh pr list --state merged --limit 500 \\
    --search "merged:2024-01-01..2024-03-31" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_2024_q1.json

■ 複数ファイルの結合（大量PR取得時）

  大量のPRを取得する場合、APIの制限により分割して取得する必要があります：

  # 期間を分けて取得
  gh pr list --state merged --limit 400 \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_part1.json

  gh pr list --state merged --limit 400 \\
    --search "merged:<=2024-06-30" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_part2.json

  gh pr list --state merged --limit 400 \\
    --search "merged:<=2024-01-01" \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_part3.json

  # jqを使って結合
  jq -s 'add' prs_part1.json prs_part2.json prs_part3.json > prs_all.json

  # 打線を生成（--repo オプションは不要）
  python3 nanj.py prs_all.json --output lineup_all.md

■ 特定条件でのPR取得

  # 特定の作者のPR
  gh pr list --state merged --author username --limit 100 \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_username.json

  # 特定のラベルを持つPR
  gh pr list --state merged --label "bug" --limit 100 \\
    --json number,title,additions,deletions,changedFiles,author,createdAt,mergedAt,headRepository,headRepositoryOwner,baseRefName,headRefName \\
    > prs_bugs.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【出力例】

  スクリプトは以下のような「なんJ風」の打線を生成します：

  1番（二）「fix: matching_preferences を rank の昇順でソート」
  [PR-10770](https://github.com/username/reponame/pull/10770)
  - 変更量 +4-1 ← これだけで仕事してて草
  - 打率.318 出塁率.412
  - **「1行で世界を変える男」**

  4番（一）「[Prod] 20251105 Release」
  [PR-11045](https://github.com/username/reponame/pull/11045)
  - 変更量 +19735-2266 ← ファッ！？
  - 打率.342 本塁打52本 OPS 1.123
  - **「圧倒的破壊力、リポジトリの四番打者」**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【トラブルシューティング】

  ▼ JSONファイルが読み込めない
    JSONの妥当性をチェック:
    $ jq '.' prs_latest.json > /dev/null && echo "JSONは有効です"

  ▼ APIレート制限に引っかかった
    GitHub APIのレート制限:
    • 認証済み: 5000リクエスト/時
    • 未認証: 60リクエスト/時

    レート制限の確認:
    $ gh api rate_limit

  ▼ 期待したPRが含まれていない
    • 検索条件やlimitの値を調整
    • --state merged が指定されているか確認
    • mergedAtフィールドがあるPRのみが使用されます

【注意事項】
  • --limit の上限は通常1000件程度です
  • 大量のPRを取得する場合はGitHub APIの制限に注意してください
  • searchクエリと組み合わせて期間を分割して取得することを推奨します
  • PRデータにはマージ済み（mergedAtフィールドがある）のものだけが使用されます

【重さの計算式】
  PR重さ = 追加行数 + 削除行数 + (変更ファイル数 × 10)

        '''
    )

    parser.add_argument(
        'input_file',
        help='PRデータが含まれるJSONファイル'
    )
    parser.add_argument(
        '--repo', '-r',
        default='username/reponame',
        help='リポジトリ名を明示的に指定（省略時はPRデータから自動検出）'
    )
    parser.add_argument(
        '--output', '-o',
        help='出力ファイルパス (指定しない場合は標準出力)'
    )
    parser.add_argument(
        '--no-claude',
        action='store_true',
        help='Claude CLIを使用せず、デフォルトのキャッチフレーズを使用'
    )
    parser.add_argument(
        '--include-merge-prs',
        action='store_true',
        help='マージPR（リリース・integration等）を除外せずに含める（デフォルトは除外）'
    )

    args = parser.parse_args()

    # ファイルの存在確認
    if not os.path.exists(args.input_file):
        print(f"❌ エラー: ファイル '{args.input_file}' が見つかりません", file=sys.stderr)
        sys.exit(1)

    # 打線生成
    use_claude = not args.no_claude
    include_merge_prs = args.include_merge_prs
    generator = NanJLineup(args.repo, use_claude=use_claude, include_merge_prs=include_merge_prs)
    result = generator.run(args.input_file)

    # 出力
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"✅ 打線を {args.output} に保存しました！", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
