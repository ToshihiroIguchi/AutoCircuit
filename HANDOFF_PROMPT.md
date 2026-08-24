# 引き継ぎプロンプト(2026-08-24、objective 軸の配線とゲート O1 時点)

このファイルは次セッションの冒頭にそのまま貼るための作業メモ。用が済んだら更新するか削除してよい。
(注:このファイルは **git 管理下**。commit すると履歴に入る。)

---

AutoCircuit プロジェクト(`C:\Users\toshi\python\AutoCircuit`)の作業を継続する。

## まず読むもの(この順で)

1. **`CLAUDE.md`** — `### Purpose` と `### Objectives` が以降の設計判断の決定基準。特に:
   - 目的3点(データから回路を探す / 回路は手段で目的は部品の中身 / 専門家が要った2工程の自動化)
   - 帰結:**入力は周波数とインピーダンスだけ**。形状も型番も部品種別も受け取らない・聞かない。
   - 帰結:**幾何不要な量は対象、絶対的な材料定数は対象外(永久に)**。
   - objective はレポートだけを変え、数値には絶対に触れない。**ゲート O1 は実装・実測済み**。
2. **`docs/HANDOFF.md`** — 現状。今回追加は §28(objective の配線とゲート O1)。
   §3 と §4 は**再導出してはいけない実測と環境の癖**。
3. 触る部分の plan doc(`CLAUDE.md` の「Start here」1〜14)。

## 直近セッション(2026-08-24)でやったこと

**コミット3本(3本目はこのファイル自身)。すべて push 済み
(= <https://toshihiroiguchi.github.io/AutoCircuit/> も更新)。`099da43` の CI は Tests・Pages
とも success(Tests 16分34秒)。**

- `c199c88` **objective 軸を core と CLI に配線し、ゲート O1 を実装・実測。**
  `core/objective.py`(レポート層)、`--objective {model,interpret}`(`fit`/`discover`)、
  `autocircuit objectives`。`--interpret` は旧綴りとして残置(隠しエイリアス)。
  `benchmarks/o1_objective.py` は**2節構成**で exit 1 する:構造(`discover()`/`fit()` が
  objective を取らず、両モジュールが objective を import しない)と実測(CLI をエンドツーエンドで
  両 objective 実行し、payload バイト一致・レポート相違)。実測 `--limit 3` で3参照系すべて合格。
  ついでに「標準誤差が値を超える」規則を `core/stats.py` の `unresolved_mask` に移動。
- `099da43` **ブラウザにも同じ質問。** `discover_interpret` → `discover_objective`
  (`BRIDGE_VERSION` 10→11)、Report 画面は `ObjectivePanel`(2ボタン切り替え、再取得のみで再探索
  しない)。実ブラウザ(Chrome)確認済み。**古いバグを1件発見して修正**:クラスが *同じゼロ* で
  一致する量(帯域上端で短絡になる回路の `r_inf`)の spread が `inf` になり、strict JSON の
  ブラウザ配線ではレスポンス全体が届かなくなっていた。

## 再導出してはいけない実測(今回追加分)

- **O1 の本体は構造側。** バイト一致は「その参照系でたまたま一致した」以上を意味しない。
  引数が存在しないことが性質を保証する。
- **`--objective` の argparse 既定値は `None`。** `"model"` を既定にすると「model を指定した」と
  「何も指定していない」が区別できず、`--interpret --objective model` が黙って通る。
- **payload 比較は時計を再帰的に落とす。** 候補ごとに `elapsed_s` があるので、トップレベルだけ
  pop しても何十箇所も差分が出る(objective とは無関係の理由で落ちるゲートは書き換えられる)。
- **`MODEL_READOUTS` は全て invariant であることをテストで確認する。** 「同値類の全メンバーが
  一致する」という見出しの下に form-dependent な数を出すのが唯一の静かな過大主張。
- **ESL は帯域上端の *見かけの* インダクタンス**(`Im Z / omega`)。直列 R-L-C では
  `L - 1/(omega^2 C)` であって `L` ではない。
- **`spread` の中央値ゼロ問題**(上記)。完全一致は中央値によらず 0。`wire.encode_payload` を
  通してからブラウザへ返す。
- **ヒアドキュメント内のバックスラッシュ n は実際の改行になって届く**(§27 と同じ罠に今回も
  1回はまった)。`chr(92)` で組むか Write ツールを使う。
- **フルスイートは専有時 10 分15 秒 / 942 pass**(`--ignore=tests/test_spice_ngspice.py`)。

## 次の作業(推奨順)

**A. 島モデル(`EVOLVE_SEARCH_PLAN.md` step 4 後半)、または step 5 の適応的簡潔性。**
EV4 第1節を開いたまま出荷してあるので、閉じにいくならここ。`populations: int`、シードごとの RNG、
世代ごとに一部交換、キャッシュは共有。ゲートは EV4 の2節と EV1 のラチェット、それに
`benchmarks/ev4_diversity.py`(対照は `_breeding_pool` の無効化で作る)。

**B. NSGA-II は「効くが急がない」。** 凍結ランドスケープで中央値 256 対 308、どちらも 120/120。
**ALPS は追加しないこと**(24/30 に悪化)。

**C. 残件。****Lin-KK の降格**、**Gamry `.DTA`・BioLogic `.mpt` リーダー**、
複数温度・複数バイアスの同時フィット(`interpret` 目的だけが得をする唯一の縮退解消手段。
`docs/OBJECTIVE_PLAN.md` §8 と `docs/HANDOFF.md` §6)。Fit 画面はまだどちらのレポートも出さない
(CLI の `fit --objective` は出す)。

**D. 探索の残り候補。** (g) beam/分枝限定、(h) VARPRO、§4.5 の段取り 23〜33%。
pool の段階化は **CPE を本当に要する参照系のアリーナが作れるまで着手しない**。

## 守ること

- 会話は日本語、コード・コメント・ドキュメント・コミットメッセージはすべて英語。
- 単純な調査は haiku、単純な実装は sonnet に委任。**報告は信じず自分で読んで再実行する。**
- 完全性保証がモード2と discovery v2 の存在意義。フィルタや枝刈りは「疑わしきは残す」。
- **緑のまま何も証明していない CI を疑う。** skip・0件・空集合は「合格」に見える。
- **安いアリーナで測って順位を決めない。**
- 実測で計画やゲートが誤っていたと判明したら、**黙って解釈を緩めず**計画側を訂正する。棄却した読み
  は消さずに並べる。
- **通知を測定として扱わない。ファイルとプロセス表だけが測定。**
- ステップ単位でコミットし、GitHub にプッシュする。**push = 公開**。
- **UI は必ず実ブラウザで確認する。**

## 環境の癖(全文は `docs/HANDOFF.md` §4)

- パッケージは pip install されていない。`$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"`
  が必須。`python -m pytest` はリポジトリルートから。
- **PowerShell でソースファイルを書き換えないこと**(cp932 で `Ω` が化ける)。編集ツールか、
  UTF-8 を明示した `python - <<'EOF'` を使う。
- CI は `ruff check .` と `mypy` を回す。`ruff format` は回していない。
- CPU を専有するベンチとテストを同時に走らせない(性能コア2)。**ブラウザを開いたまま回さない。**
- **長時間ジョブはハーネスの `run_in_background` で回し、結果は出力ファイルを読む。**
- **Bash ツールから `wsl` を呼んではいけない。** ngspice は WSL の Ubuntu-24.04 にのみある。

### Web UI

```powershell
cd web; npm run dev      # http://localhost:5173(Python は起動時に固まる。編集したら再起動)
npm run smoke            # Python 側の経路を Pyodide でヘッドレス検証
npm run check            # tsc + 回路図ジオメトリ + サンプル照合
```

- **bridge の操作を増やしたら `src/autocircuit/web/light.py` と `web/src/worker/protocol.ts` の
  `BRIDGE_VERSION` を両方上げる。** ただし**同じ編集で版を上げてもフィールド追加の skew は
  捕まらない**(§26)。
- **ブラウザ自動化のスクリーンショットとダウンロードは `.playwright-mcp/` に落ちる。終わったら消す。**
