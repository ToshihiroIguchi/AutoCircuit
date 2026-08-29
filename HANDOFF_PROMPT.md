# 引き継ぎプロンプト(2026-08-29、AutoEIS 比較ラウンド:ステップ0完了・ステップ1途中)

このファイルは次セッションの冒頭にそのまま貼るための作業メモ。用が済んだら更新するか削除してよい。
(注:このファイルは **git 管理下**。commit すると履歴に入る。)

---

AutoCircuit プロジェクト(`C:\Users\toshi\python\AutoCircuit`)の作業を継続する。
今回のタスクは **`docs/AUTOEIS_COMPARISON_PLAN.md` の実行**。

## まず読むもの(この順で)

1. **`docs/AUTOEIS_COMPARISON.md`** — **ステップ0の実測結果**。ここに書いてある数字は再導出しない。
2. **`docs/AUTOEIS_COMPARISON_PLAN.md`** — 計画。**`[corrected by step 0]` の段落**が、実測が計画を
   否定した箇所。元の記述は消していないので両方読むこと。
3. `CLAUDE.md` の `### Purpose`(特に目的3点目)。比較が**既定値どうし**である理由。
4. `docs/HANDOFF.md` §3(再導出禁止の実測)と §4(環境の癖)。
5. `docs/SEARCH_ALGORITHM_SCREENING.md` §1 と §4.2 — 壁時計予算と安いアリーナがどちらも嘘をつく話。

## 現在地(コミット済み)

**ステップ0とステップ1は完了。配管は全部そろっていて、残るのは本番ランと結果の記述だけ。**

- `f07d6d9` ステップ0(go/no-go)= **go**
- `f64404e` `translate.py` + 40テスト
- `77a4234` `arena.py`(アリーナCの事前登録)+ 相手フィルタと1020件一致
- `d012d88` 引継ぎ
- `d8adc66` 生産者2本 + NUTS 段の実費 + arviz 障害
- `e2f6ef9` サンプラーの重複バグ修正
- `05ff924` `score.py` + テスト
- `7d6e0a2` 実行手順
- `541edc8` アリーナCの実体と、その偏りの記録
- `c117f65` `d` の表示バグ修正(既知解フィクスチャで通し検証済み)

**アリーナCは生成済み**(`benchmarks/autoeis_round/arena_c/`、8真値×20シード=160スペクトル。
`.gitignore` 済みだが `arena_c_manifest.json` が履歴にある。消えたら `arena.py` を同じ
`ARENA_SEED` で回せば同じものが出る)。

**残っているのはこれだけ:**

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
# 1. AutoCircuit 側(済んだ分は自動で飛ばす)。1件 208 s(3素子)〜。
python benchmarks/autoeis_round/run_autocircuit.py --arena benchmarks/autoeis_round/arena_c --max-seeds 5 --workers 6
# 2. AutoEIS 側。1件約40分 × 40 ≈ 26 時間。**1と同時に走らせない。**
C:\Users\toshi\python\autoeis-env\Scripts\python.exe benchmarks/autoeis_round/run_autoeis.py --arena benchmarks/autoeis_round/arena_c --max-seeds 5
# 3. 採点(smoke レコードがあると実行を拒否する)
python benchmarks/autoeis_round/score.py --arena benchmarks/autoeis_round/arena_c --out benchmarks/autoeis_round/arena_c/report.json
```

長時間ジョブは切り離して起動する(親シェルが死んでも生き残ることを実測済み):

```powershell
Start-Process -FilePath python.exe -ArgumentList "benchmarks/autoeis_round/run_autocircuit.py","--arena","benchmarks/autoeis_round/arena_c","--max-seeds","5","--workers","6" `
  -WorkingDirectory C:\Users\toshi\python\AutoCircuit -RedirectStandardOutput run_ac.log -RedirectStandardError run_ac.log.err -WindowStyle Hidden
```

**そのあと:** `docs/AUTOEIS_COMPARISON.md` に §2 として結果を書く → `IMPLEMENTATION_PLAN.md` の
先行研究段落、`SEARCH_ALGORITHM_SURVEY.md` 85行目、`HANDOFF.md` の新節、**結果が出てから**
`CLAUDE.md` の Start here 15番。

## 環境(構築済み。作り直さないこと)

AutoEIS は**プロジェクト外の隔離 venv** に入っている。`pyproject.toml` には絶対に足さない。

```
C:\Users\toshi\python\autoeis-env\Scripts\python.exe   # autoeis 0.0.44, Python 3.12.10
```

Python 3.12 が必要(`autoeis` は `requires_python <3.13`。この機械の既定は 3.13)。Julia 1.10.12 と
EquivalentCircuits.jl 0.3.1@master は `juliapkg` が取得済み。全版は
`docs/AUTOEIS_COMPARISON.md` §0.1。

## 運転条件(今回の設計を縛っている)

- **機械が途中で落ちうる。失ってよい計算は3時間まで。**
- **Claude 側も5時間制限で止まりうる。** よってラウンドの進行が Claude の生存に依存してはいけない。
- 帰結:生産者は**単体スクリプト**で、**1実行ごとに JSONL へ追記して fsync**、再実行で**済んだ分を
  飛ばして続行**する。ユーザーが自分で起動して放置できること。長時間ジョブは Claude のツールから
  起動せず、**ユーザーに `!` 付きで叩いてもらう**のが安全。

## ステップ0で分かった、この先ずっと効く事実(再導出禁止)

- **語彙は `R,C,L,P(CPE)` のみ。`W` は無い。** 既定 `terminals="RLP"` は `C` を含まず、
  `capacitance_filter` が理想 `C` を含む回路を全排除する。
- **この repo の6参照系は全部 `oov` か `filtered`。アリーナ A は空。回収率が存在するのは
  アリーナ C だけ。**
- **既定経路はシードが効かない**(同一シードで結果不一致を実測)。AutoEIS の各実行は独立ドロー。
  `seed=0` は時刻にフォールバックするので使わない。
- **1スペクトル約35分**(GEP 段のみ、`iters=100`)。**NUTS 段はまだ未計測**。総額はこれより増える。
- **AutoEIS は探索前にデータを削る。** 前処理3段が誘導性の尾を消すので、`L` を含む真値では探索は
  `L` の証拠を見ない。`filtered` とは別の事象。
- `perform_full_analysis()` は `NotImplementedError`。既定経路は4段の逐次呼び出し。
- 相手の順位規則は `WAIC (sum)` 昇順(`visualization.py`)。これが `recommended` の定義。
- CPE の定義は両者一致(`Z = 1/(Q(jω)^n)`)。単位換算不要。
- 構造フィルタ(直列オーミック抵抗・並列経路)の自前実装は、**相手の関数と1020件で完全一致を実測済み**。

## 結果を読むときに外してはいけないこと

- **`d = 6`。これは検定固有の下限でアリーナの大きさではない。** 片方向に揃った不一致5組は
  p = 0.0625 にしか届かない。シードを足すと「不一致が出る機会」が増えるだけで、**バーは下がらない**。
- **アリーナは8真値中6本が `L` を含む。** 相手は前処理で誘導性の尾を削るので、全体の数字は相手の
  **前処理**を測ってしまう。**`L` 無し群(2真値)が探索の比較、`L` 有り群が前処理効果**として読む。
  5シードでは `L` 無し群は10ペアしかなく、ほぼ何も解像しない。20シードで40ペア。
  **アリーナを引き直してはいけない**(`docs/AUTOEIS_COMPARISON.md` §1.3)。
- **`reported` は2通り出る。** `refitted`(両側とも同じ fitter で再フィット=トポロジーの問い)と
  `as_returned`(各ツール自身の値)。どちらか一方を見出しにしない。
- `oov` は分母から外す。0点にしない。`filtered` を `wrong` に混ぜない。

## この比較で絶対に守ること

- **語彙外は N/A であって 0 ではない。** 相手が持たない段(こちらの事後分布の不在も同じ)を点数に
  したら測定ではなく機能表。
- **既定値どうしで比べる。** チューニングしたアームは別ラベルで、見出しにしない。
- **審判は両側に同じものを当てる。** 自分にだけ同値検出を使ったら審判を採点している。
- **本命はアリーナ C。** A はフィクスチャを書いた者を測る(そもそも今回は空)。
- **時間は説明であって見出しではない。** 速度比は結論のどの文にも書かない。
- **`d`(分解能)を走らせる前に結果ファイルに書く。** 差が `d` の内側なら結論は「このシード数では
  区別がつかない」で、対応はシードを増やすか何もしないか。**バーを書き直すことではない。**
- **停止は機械の都合だけで決める。結果が良く見えたからという理由で止めない。** シード列(1〜20)と
  ステージ境界(5/10/20)は `arena.py` に固定済み。
- **これはゲートではなく記述。この結果でこの repo の既定値は1つも変えない。**

## この比較が終わっても言えないこと(計画 §7)

合成の真値は部品ではない。これは**2つのツールの既定値を、2つの版で、1台の機械で**比べたもので、
「遺伝的プログラミング対網羅列挙」の比較ではない。事後分布の質は比較できないし、こちらに事後分布が
無いことを点数の入った文に混ぜてはいけない。引き分けはどちらの検証でもない。

## 比較ラウンドの外に残っている作業(持ち越し)

- **A. Lin-KK の降格**、**Gamry `.DTA` / BioLogic `.mpt` リーダー**、複数温度・複数バイアスの
  同時フィット(`OBJECTIVE_PLAN.md` §8)。Fit 画面はまだどちらの objective レポートも出さない。
- **B. NSGA-II は「効くが急がない」**。**ALPS は追加しないこと**(24/30 に悪化)。
- **C. 探索の残り候補**:(g) beam/分枝限定、(h) VARPRO。pool の段階化は **CPE を本当に要する
  参照系のアリーナが作れるまで着手しない**。

## 守ること

- 会話は日本語、コード・コメント・ドキュメント・コミットメッセージはすべて英語。
- 単純な調査は haiku、単純な実装は sonnet に委任。**報告は信じず自分で読んで再実行する。**
- **緑のまま何も証明していない CI を疑う。** skip・0件・空集合は「合格」に見える。
- 実測で計画やゲートが誤っていたと判明したら、**黙って解釈を緩めず**計画側を訂正する。棄却した読み
  は消さずに並べる。
- **通知を測定として扱わない。ファイルとプロセス表だけが測定。**
- ステップ単位でコミットし、GitHub にプッシュする。**push = 公開**。

## 環境の癖(全文は `docs/HANDOFF.md` §4)

- パッケージは pip install されていない。`$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"`
  が必須。`python -m pytest` はリポジトリルートから。
- **PowerShell でソースファイルを書き換えないこと**(cp932 で `Ω` が化ける)。
- CI は `ruff check .` と `mypy` を回す。
- CPU を専有するベンチとテストを同時に走らせない(実コア10・論理12)。**ブラウザを開いたまま回さない。**
- **Bash ツールから `wsl` を呼んではいけない。**
- **AutoEIS の並列は Julia `Distributed`。** 親の Python プロセスは CPU をほぼ使わない。これは
  正常であって停止ではない(一度これで誤診した。`docs/AUTOEIS_COMPARISON.md` §0.3)。
