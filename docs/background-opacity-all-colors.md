# 任意のセル背景色への opacity 適用

## 設定

この変更をビルドした kitty の `kitty.conf` に追加する:

```conf
background_opacity 0.4
background_opacity_all_colors yes
linux_display_server wayland
# 起動後に opacity 自体も変えたい場合のみ:
# dynamic_background_opacity yes
```

- `background_opacity_all_colors` の初期値は `no`。無効時は従来のまま。
- 有効時は既定色、256色、24-bit RGB、アプリの反転背景すべてに `background_opacity` を適用する。色数制限はない。
- `transparent_background_colors`（アプリが制御コードで指定したものを含む）の個別 opacity より、この設定を優先する。
- 設定の再読み込みで有効／無効を切り替えられる。ただし透過可能な OS ウィンドウの確保は起動時の設定に依存する。最初から `background_opacity < 1` または `dynamic_background_opacity yes` で起動すること。
- ユーザーとの確認に従い、kitty の選択ハイライトとカーソルは既存の扱いを維持する。アプリの通常の反転表示は透過する。
- アプリの設定変更は不要。背景色を端末の既定色に揃える必要もない。

## 調査・設計

作業開始時点で `/home/user/Code/kitty` は upstream のクリーンな clone だったため、それを利用した。ベースは `32a77d3cf`。

このリビジョンは `kitty/shaders/*.slang` を Slang コンパイラーで OpenGL 用 GLSL に変換する。

1. `shaders.c:cell_update_uniform_block()` が OS ウィンドウの実効アルファと色を GPU に渡す。
2. `background.slang:compute_background()` がセルの色、反転、選択、カーソルを解決する。従来は既定色＋最大7個の `transparent_background_colors` にだけ opacity を設定する。
3. `cell.slang` が背景を `(B * a, a)` にし、グリフ／装飾の coverage を別に求めて premultiplied-alpha 合成する。
4. 画像が文字と背景の間にある場合は BG／画像／FG の別パスを使用する。padding も共有の背景計算を使用する。
5. 最終 blit は線形 RGB を premultiplied sRGB に変換し、Wayland compositor が背後と合成する。

変更は共有背景計算への一様なフラグ追加だけに絞った。色のリストを増やす方式では全24-bit色を扱えず、最終ウィンドウ全体の opacity を下げる方式では文字まで薄くなるため、どちらも使っていない。

文字の coverage を `t`、背景 opacity を `a` とすると出力は:

```text
RGBpremul = F * t + B * a * (1 - t)
alpha     = t + a * (1 - t)
```

したがって文字内部 (`t=1`) は不透明、背景 (`t=0`) は指定のアルファ、文字の縁は既存のアンチエイリアスを維持する。文字の gamma／contrast 計算、画像シェーダー、最終画像全体の opacity は変更していない。

## 変更ファイル

| ファイル | 内容 |
| --- | --- |
| `kitty/options/definition.py` | 新設定、初期値、説明、既存設定との関係 |
| `kitty/options/types.py` | 生成された Python 設定型 |
| `kitty/options/parse.py` | 生成された設定パーサー |
| `kitty/options/to-c-generated.h` | 生成された Python → C 設定変換 |
| `kitty/state.h` | C の Options に bool を追加 |
| `kitty/shaders.c` | GPU uniform の C 側ミラーとフラグの設定 |
| `kitty/shaders/background.slang` | 全色の opacity 適用、反転背景の例外解除。無効時は元の色照合を使用 |
| `kitty_tests/options.py` | 初期値、yes/no、既存設定との併用、C 変換のテスト |
| `kitty_tests/manual_background_opacity.py` | 実 Wayland ウィンドウから RGBA を取得する再現可能なテスト |
| `docs/background-opacity-all-colors.md` | 本報告 |

GPU の uniform レイアウトは Slang と C の双方を同時に変更した。生成された GLSL／ビルド成果物は追跡ファイルに追加していない。

## ビルド・起動

通常の upstream の開発ビルド方法:

```sh
cd /home/user/Code/kitty
./dev.sh build
kitty/launcher/kitty --config NONE \
  -o linux_display_server=wayland \
  -o background_opacity=0.4 \
  -o background_opacity_all_colors=yes nvim
```

末尾の `nvim` は `lazygit`、`yazi`、または任意のコマンドに置き換えられる。`--config NONE` を省けば通常の `kitty.conf` を使う。システムにインストールされた別の kitty ではなく、この launcher を起動すること。

この NixOS 環境では既存の `shell.nix` を使用してソースからビルドした:

```sh
nix-shell --run 'python setup.py build'
```

実際の最終ビルドでは既にインストールされていた Go 1.27.1 の `bin` を PATH の先頭に置き、`GOTOOLCHAIN=local` を指定した。既定の Go 1.26.7 では upstream の `toolchain go1.26.9` により追加ダウンロードが発生する。C、Wayland backend、GLSL/SPIR-V、Go の kitten を含めてビルド完了。

設定生成は、最初のビルド後に `kitty/launcher/kitty +launch gen config` で実行した（`ruff` と `clang-format` を PATH に追加）。通常の `python gen config` はこの upstream リビジョンで assertion に失敗するため、kitty の launch 環境を使う。設定生成後に再ビルド済み。

## 検証結果

AMD Radeon / Mesa 26.2.3、実際の niri Wayland セッションで確認。

```sh
nix-shell --run 'kitty/launcher/kitty +launch test.py --module options'
nix-shell --run 'kitty/launcher/kitty +launch test.py --module slang'
nix-shell --run 'kitty/launcher/kitty +launch test.py --module graphics'
nix-shell --run 'kitty/launcher/kitty +launch test.py --module screen'
nix-shell --run 'python kitty_tests/manual_background_opacity.py'
```

- options: 8件、slang: 18件、graphics: 35件、screen: 59件、すべて成功。
- 16種類の truecolor 背景＋反転背景＋indexed 背景について `a=0.4` の RGB／alpha を確認。背景色を消さず、premultiplied RGB が元の色×opacity であることを検証。
- `a=0`、`a=1` も成功。`a=0` では色の復元は不可能なので、背景 alpha と文字を検証。
- 文字内部は alpha=255、アンチエイリアス部分は背景と不透明の間の alpha。
- 無効時は未指定色が不透明に復帰し、個別指定した色は従来通り `a=0.8`。
- 設定再読み込みの on → off → on が成功。
- 負／正の z-index の画像を表示した別パスでも成功。画像とブロックカーソルの内部 alpha=255 を確認。
- Neovim（`--clean`、habamax）、lazygit、yazi を実際に起動し、アプリ背景の複数色が有効時は alpha=102、無効時は従来の不透明背景に戻ることをスクリーンショットで確認。
- 動的 opacity を 0 → 0.4 に変更し、niri の最終スクリーン画像と kitty の RGBA を比較。2,965個の背景サンプルが `sourcepremul + backdrop * (1-a)` と一致（最大誤差0）、白い文字内部6,832画素も不透明を維持した。ただしこのセッションの背後は黒一色で、画像の壁紙による目視確認は未実施。
- `git diff --check`、変更したテストの Ruff check 成功。

実測成果物（このマシンの一時ディレクトリ）:

- セル／画像／再読み込み: `/tmp/kitty-opacity-w77w2xh5/`
- Neovim／lazygit／yazi: `/tmp/kitty-app-opacity-wz3wuwy6/`
- niri 最終合成: `/tmp/kitty-compositor-ciyzjuw2/`

注意: 現 upstream の **非縮小** remote screenshot は最終 framebuffer を直接読み出すため、保存 PNG の RGB も premultiplied sRGB。その PNG を通常の画像ビューアーで開くとさらに暗く見える場合がある。画素テストはこの仕様を考慮している。niri の画面キャプチャは合成後の画像なので、その問題はない。

## 制約

- OS/compositor が透過をサポートすることが必要。壁紙そのものの描画・設定は niri 側の責任で、kitty は追加しない。
- 選択・カーソルは意図的な例外。既存のフェード、DIM、blink、`inactive_text_alpha`、カラーグリフの固有 alpha は尊重し、強制的に不透明化しない。
- `background_image` 自体の opacity は変更しない。壁紙を見る用途では kitty 側の不透明な背景画像を使わないこと。
- 画像の配置・z-index は従来のまま。ただし背景が透過する結果、従来背景に隠れていた下層の画像が見えるのは意図した動作。
- 小さい opacity では背景色の見た目と文字のコントラストが壁紙に左右される。背後の色は kitty から取得できないため、文字の既存 gamma／contrast 調整は指定セル色を基準にする。
- 全アプリ・全GPU・全プラットフォームでの網羅試験、選択操作やすべてのカーソル形状の目視試験、性能ベンチマークは未実施。既存の背景透過に伴う描画コストは残る。
