# 引き継ぎプロンプト(2026-08-15、Node 20 対応 + README リンク 完了時点)

このファイルは git 管理外の作業メモ。次セッションの冒頭に以下をそのまま貼る。用が済んだら削除してよい。

---

AutoCircuit プロジェクト(`C:\Users\toshi\python\AutoCircuit`)の作業を継続する。

## まず読むもの(この順で)

1. `CLAUDE.md` — 規約。「Three modes」直後の「A user-supplied constraint narrows what the report is
   allowed to claim」の段落が、モード2でもステップ4の中断処理でもステップ5の除外パスでも、そして
   今回の CI ゲートでも実際に効いた原則。
2. `docs/HANDOFF.md` — 現状。§3(再導出してはいけない実測)、§4(環境の癖)、§7(モード2)、
   §8〜§14(Web UI ステップ1〜7)、§15(ngspice 往復と初のテスト用ワークフロー)、
   **§16(Node 20 離脱と README、新設)**。
3. `docs/IMPLEMENTATION_PLAN.md` §7 — SPICE export。ngspice 往復の実測がここに入った。
4. `docs/WEB_UI_PLAN.md` — **phase 6 は完了。全7ステップ、全ゲート決着済み。**
   §2.3(Node の数字がブラウザで3倍外れていた)、§2.4(フィット結果はインタプリタ間でビット一致しない)、
   §2.5(ゲート W2 の一条項が達成不能だと判明)、§2.6(止められる報告は弱い文を必要とする)、
   §2.7(2つのゲートを開けたまま出荷し、そう書いた)、§2.8(その2つを逆方向に決着させた)、
   §6 がゲート一覧。
5. `web/README.md` — ブラウザ側の地図。4画面、テーマの規則、`public/` に何が生成されるか。

`docs/PARTIAL_TOPOLOGY_PLAN.md` と `docs/DISCOVERY_V2_PLAN.md` は完了済み。訂正記録として読む価値は
あるが着手対象ではない。

## 現状

- **サイトは公開済み: <https://toshihiroiguchi.github.io/AutoCircuit/>**
  `.github/workflows/pages.yml` が `main` への push ごとにビルドして公開する。`tsc --noEmit` と
  `npm run smoke` がゲート。**push は「保存」ではなく「公開」。**
- **ワークフローは2本。**`pages.yml`(公開)と `tests.yml`(ruff / mypy / フルスイート /
  ngspice 往復)。両方 push ごとに走る。**Node 20 の非推奨注釈は解消済み**(§16。
  `checkout@v7` / `setup-python@v7` / `setup-node@v7` / `upload-pages-artifact@v5` /
  `deploy-pages@v5`)。
- CLI バックエンド完成、**712 テスト**(うち 19 は ngspice 往復で、**Windows では skip**。
  CI では全 712 が走り 417 s と 520 s ― 同じスイートで別ランナー。**壁時計差を回帰と読まない**)。
  discovery v2 は G1〜G5、モード2 は P1〜P4 実測済み。
- **README はサイトにリンク済み**で、`## In the browser` 節がある。そこに書いたコールドスタートは
  公開 URL からの 21 s(キャッシュ後 5〜11 s)で、`localhost` の 5 s ではない。混ぜないこと。
- **phase 6 は完了。W1・W2・W4・W6 合格、W3 は条件付き合格、W5 は撤回。**
  - **W3(コールドスタート)**:ビルド時にバイトコードを作って配る変更で **約2倍**改善。
    休んだマシンで 4.9〜5.7 s(初回フィット完了まで約6.6 s)、**負荷のかかったマシンで 10.9 s
    (同 約13 s)**。10秒の目標はマシンの2倍ドリフトの内側に入った、というのが結論。
    片方だけ報告しないこと。次に効くのは wheel 展開(2.2〜4.4 s)と転送量(サイト全体41 MB)。
  - **W5(オフライン / `file://`)は撤回**。`file://` はどんな梱包でも不可能(実測)。オフラインは
    Service Worker があれば可能だが、**やらないと決めた**(push ごとに公開するサイトと訪問者の
    間にキャッシュを挟むことになるため)。
- **SPICE export は方言としても正しいことが実測された(§15)。**
- 低優先の残件:Gamry `.DTA` / BioLogic `.mpt` リーダー(実ファイル入手後)。

## 前セッションでやったこと(Node 20 離脱 + README リンク)

コミット `02a83f7` と `fa9505f`。**計算内容は何も変えていない。**

- 両ワークフローの5つの action を現行メジャーへ。**対象はファイルを読むと3つ、注釈を読むと5つ**
  だった(`upload-pages-artifact@v3` の内部の `upload-artifact@v4`、別ジョブの `deploy-pages@v4`)。
  注釈は `gh api repos/OWNER/REPO/check-runs/<job-id>/annotations` をジョブごとに叩いて読む。
- **押す前に「注釈3件」を実測してから押し、押した後に「0件」を実測した。**両方とも前から緑なので、
  緑は測定にならない。
- `upload-pages-artifact@v4` は**隠しファイルをアーティファクトに入れない**。`web/dist` の唯一の
  ドットファイルは `.bytecode-stamp`(`scripts/precompile.mjs` 用、ブラウザは fetch しない)。
  公開サイトで全アセット 200 / `.bytecode-stamp` のみ 404 を実測。**サイトが配信するドットファイルが
  今後できたら `include-hidden-files: true` が要る。**
- deploy action がメジャー更新されたので、**実ブラウザでも確認した**(Randles 例 → `generic_csv`
  71点 → Lin-KK PASS、Voigt 16)。緑の deploy ステップは検証ではない。
- README にサイトへのリンクと `## In the browser` 節。Install 節の「run in a browser under
  Pyodide **later**」が公開済みのいま偽になっていたので直した。

## その前のセッション(ngspice CI 往復)

`tests/test_spice_ngspice.py` と `.github/workflows/tests.yml`。計算内容は何も変えていない。
netlist に「駆動する deck」のコメントが増えた(`core/spice.py` の `_how_to_drive()`)。

- 9回路を export し、実物の **ngspice 42** で AC スイープして**バイナリ raw ファイル**を読み戻す。
- **比較相手はモデルではなく `test_spice.py` 自身の節点解析エンジン。ここが設計の核心。**
  モデル相手だとラダー合成の誤差が ~1e-2 で居座り、その3桁下の方言バグを完全に隠す。
  エンジン相手なら合成誤差が厳密に相殺され、残るのは「ファイルの読まれ方」だけになる。
- netlist が自分を駆動する deck を持つようになった(このフィット自身の帯域入りの `.ac` 行と
  DC 開放の注記)。2端子 `.subckt` だけ渡すと両方を推測させることになる。

## 再導出してはいけない実測結果(今回追加分)

古い分は `docs/HANDOFF.md` §3 と §8〜§14、Node 20 の分は §16。ngspice 分は §15 で、特に効くもの:

- **ngspice は動作点に失敗しても exit 0 を返す。** コンデンサで始まるモデルは全て DC 開放なので
  特異行列になり、gmin stepping も source stepping も失敗する — それでも AC 解は 4.5e-12 で正しい
  (線形回路なので動作点に依存しない)。**終了コードで判定する往復テストなら、ngspice が匙を
  投げた deck を「合格」と呼んでいた。**だから診断メッセージ側を assert している。
- **`.option rshunt=1e12` は警告を消すが、ここでは誤った処方。** |Z| を最大 **7.2e-7** 動かし、
  測ろうとしている量より5桁悪い。しかも単純な |Z|/R ではない(ラダーの内部ノードも分流される
  ため、CPE ケースはポート単独の予測の10倍)。**テスト deck は一切の助けを足さない。**
- **未知の素子は `Error on line` / exit 1 / raw ファイルを一切書かない。** raw ファイル欠如は
  「比較対象なし」ではなく失敗として扱うこと。
- **一致は抵抗単体で厳密に0、他8件で 4.6e-15 〜 4.5e-12。**閾値は 1e-9。ラダーの値は
  scipy 1.11 と 1.17 で末尾が違うが、一致度は動かない — このテストが「中身」ではなく
  「読まれ方」の話であることの意味。
- **skip したテストは pass に見える。** `tests.yml` の往復ステップはサマリに `skipped` があれば
  落とす。押す前に `/usr/bin/ngspice` を隠して両方向を実測した(あり:19 passed / exit 0、
  なし:19 skipped / **exit 1**)。この形の失敗はこのプロジェクトで既に4回起きている。
- **壁時計テストは2回目の熱失敗を観測した。** `test_time_limit_stops_the_search` が
  フルスイート中に 67.1 s で落ち、単独では 48.1 s で通った。**境界は広げない。**

## 次の作業(候補・要相談)

1. Gamry `.DTA` / BioLogic `.mpt` リーダー(実ファイルが要る。無いと仕様推測になる)。
2. コールドスタートの続き(wheel 展開 2.2〜4.4 s と転送量 41 MB)。W3 をマシンドリフトの
   外に出したいなら。**下調べ済み(実測)**:`web/dist` 41 MB の内訳は scipy wheel 13.36 MB
   (展開後 **45 MB**)、`pyodide.asm.wasm` 9.15、`python_stdlib.zip` 6.73、
   `pyodide-bytecode.zip` 5.52、numpy wheel 2.78、アプリ JS 1.34。この package が import する
   scipy は `optimize` / `linalg` / `signal` / `special` の4つだけで、未使用の大物は
   `stats` 1.72 MB(展開 6.59)、`spatial` 1.04(3.66)、`io` 0.49(1.76)。wheel を削るのは
   転送量と展開時間の両方に効く唯一のレバーだが、**消えた submodule は実行時にしか出ない**ので、
   削る前に「必要な subpackage を削ると `npm run smoke` が実際に赤くなる」ことを先に確かめる。
3. ~~Node 20 deprecation の対応~~ **完了(§16)**。注釈を読むと対象は3つではなく5つだった
   (`upload-pages-artifact@v3` の内部の `upload-artifact@v4` と、別ジョブの `deploy-pages@v4`)。
   `checkout@v7` / `setup-python@v7` / `setup-node@v7` / `upload-pages-artifact@v5` /
   `deploy-pages@v5` に更新。**注釈 3件 → 0件を実測**、実ブラウザでも確認済み。

## 守ること

- 会話は日本語、コード・コメント・ドキュメントはすべて英語。
- 単純な調査は haiku、単純な実装は sonnet に委任。委任時は必ず「テストが落ちたらアサーションを弱めず、
  ライブラリのバグを疑って xfail で残し報告せよ」と指示する。**報告は信じず自分で読んで再実行する。**
- 完全性保証がモード2と discovery v2 の存在意義。フィルタや枝刈りは「疑わしきは残す」。
- **緑のまま何も証明していない CI を疑う。**skip・0件・空集合は「合格」に見える。
- 実測で計画やゲートが誤っていたと判明したら、**黙って解釈を緩めず**計画側を訂正するコミットを残す。
- ステップ単位でコミットし、GitHub にプッシュする。**push = 公開**であることを忘れない。
- **UI は必ず実ブラウザで確認する。**

## 環境の癖(`docs/HANDOFF.md` §4 に全部ある。特に効くもの)

- パッケージは pip install されていない。`$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"`
  が必須。`python -m pytest` は必ずリポジトリルートから。
- **PowerShell でソースファイルを書き換えないこと。**`Get-Content -Raw` は cp932 として読むので
  `Ω` が化ける。編集ツールか、符号化を明示した Python を使う。
- PowerShell は二重引用符を含むヒアドキュメントを壊す。コミットメッセージも一時ファイルに書いて
  `git commit -F`。
- CPU を専有するベンチとテストを同時に走らせない。長時間の計測はデタッチ起動。

### ngspice(今回追加)

- **Windows には ngspice が無く、winget にも無い。**WSL の Ubuntu-24.04 に
  `apt-get install ngspice` で入れてある(CI の `ubuntu-latest` と同じ ngspice 42)。
  `python3-numpy` / `python3-scipy` / `python3-pytest` も入れてある(numpy 1.26 / scipy 1.11 で、
  Windows 側の 2.5 / 1.17 とは別 — 第二のインタプリタとして使える)。
- 手元で回す:
  ```powershell
  wsl -d Ubuntu-24.04 bash -lc "cd /mnt/c/Users/toshi/python/AutoCircuit && PYTHONPATH=`$PWD/src python3 -m pytest tests/test_spice_ngspice.py -q"
  ```
  約1秒。引用符が絡むものはスクリプトファイルに書いて `wsl -d Ubuntu-24.04 bash <path>` で呼ぶ。
- **Bash ツールから `wsl` を呼んではいけない。**Git Bash が `/mnt/c/...` を
  `C:/Program Files/Git/mnt/c/...` に書き換えてパスが見つからなくなる。PowerShell から呼ぶこと。

### Web UI 特有

```powershell
cd web; npm run dev      # http://localhost:5173
npm run smoke            # Python 側の経路を Pyodide でヘッドレス検証(overlay も適用される)
npm run build            # -> web/dist/
npx tsc --noEmit -p tsconfig.json
```

- `web/public/` は生成物(約40 MB、gitignore)。`web/.build/autocircuit-source.zip` は precompile の
  入力で、`public/autocircuit-src.zip` はその出力。**この2つを同じパスにしないこと**(同じにすると
  2回目の `npm run assets` がバイトコードを黙って捨てる)。
- `npm run assets` は Pyodide も起動する(約30 s)。`web/public/.bytecode-stamp` が一致すれば飛ばす。
- **bridge の操作を増やしたら `src/autocircuit/web/bridge.py` と `web/src/worker/protocol.ts` の
  `BRIDGE_VERSION` を両方上げる。**片方だけだとページが起動を拒否する(設計どおり)。
- `benchmarks/pyodide/src.zip` は自動更新されない。W1 ベンチ前に `python make_zip.py` で作り直す。
- **ブラウザ自動化のスクリーンショットとダウンロードはリポジトリ直下(`.playwright-mcp/`)に落ちる。
  終わったら消す。**
