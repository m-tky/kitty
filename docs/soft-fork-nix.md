# Nix / NixOS / Home Manager と週次追従

## 公開前提

このリポジトリを自分の GitHub fork に commit/push する。以下の `OWNER/kitty` はその公開先に置き換える。現在の作業環境の `origin` は upstream のままであり、この変更は remote の変更や GitHub 設定の変更を行わない。

`flake.nix`、`flake.lock`、`nix/`、専用 workflow と背景透過の変更をすべて commit すること。Git の flake は未追跡ファイルを含めない。

## パッケージを使う

Linux の `x86_64-linux` / `aarch64-linux` を公開する:

```sh
nix build github:OWNER/kitty#kitty
nix run github:OWNER/kitty
# 開発・ローカル変更を含めて試す（commit前の作業ツリーにも対応）:
nix build "path:$PWD#kitty"
nix develop "path:$PWD"
```

flake 出力:

- `packages.<system>.kitty` / `default`: この fork のソースをビルドした kitty。
- `apps.<system>.kitty` / `default`: 同じ kitty の起動。
- `overlays.default`: `pkgs.kitty-soft-fork` を追加。既存 `pkgs.kitty` は置き換えない。
- `nixosModules.default`: opt-in のシステムインストール用モジュール。
- `homeManagerModules.default`: Home Manager の kitty パッケージの既定値を差し替える。
- `checks.<system>.package`: 実パッケージのビルド＋描画関連の120件のテスト。
- `packages.<system>.go-modules`: 固定出力の Go 依存。

この fork のソースを、lock した Nixpkgs の kitty パッケージ定義でビルドする。Nixpkgs の runtime ライブラリパス設定、desktop entry、terminfo、shell integration、kitten のパッケージングを再利用する。Go の vendor hash は upstream のリリース用 hash を流用せず、`nix/go-deps-hash.nix` にこの fork の依存内容を固定する。Slang コンパイラーを含め、sandbox 内でソースから構築する。テストは `options` / `slang` / `graphics` / `screen` の120件を実行する。Nixpkgs から継承する全件の installCheck は `/etc/machine-id` やホストの cgroup/proc 情報を要求して sandbox 内で失敗するため無効化し、この4モジュールの checkPhase に置き換えている。

### NixOS

自分の設定 flake の inputs に追加する（この fork 自体の Nixpkgs pin を維持する例）:

```nix
inputs.kitty-soft-fork.url = "github:OWNER/kitty";
```

`nixosSystem` に渡す modules 内で:

```nix
{
  environment.systemPackages = [
    inputs.kitty-soft-fork.packages.${pkgs.stdenv.hostPlatform.system}.kitty
  ];
}
```

または専用モジュールを使う:

```nix
modules = [
  inputs.kitty-soft-fork.nixosModules.default
  { programs.kitty-soft-fork.enable = true; }
];
```

これはシステムへのアプリ追加だけを行い、ユーザーの `kitty.conf` は変更しない。通常版と同じ `kitty` / `kitten` バイナリ名なので、通常版と同時にインストールしないこと。

### Home Manager

既存のモジュールをそのまま使う:

```nix
{
  programs.kitty = {
    enable = true;
    package = inputs.kitty-soft-fork.packages.${pkgs.stdenv.hostPlatform.system}.kitty;
    settings = {
      background_opacity = "0.4";
      background_opacity_all_colors = "yes";
      linux_display_server = "wayland";
    };
  };
}
```

または HM 設定の `imports` に `inputs.kitty-soft-fork.homeManagerModules.default` を追加すれば、`package` 指定を省略できる。`enable` は明示的に設定する。

overlay を使う場合は自分の設定に `nixpkgs.overlays = [ inputs.kitty-soft-fork.overlays.default ];` を追加し、`pkgs.kitty-soft-fork` を指定する。overlay は利用側の Nixpkgs を使用するため、古い Nixpkgs との互換性は保証しない。lock した package 出力の直接利用を推奨する。

## 週次自動追従

`.github/workflows/soft-fork-sync.yml` は毎週月曜03:15 UTC（日本時間12:15）と手動実行に対応する。

1. 配布先はリポジトリの default branch。作業先は `automation/upstream-sync`。
2. 既存の更新ブランチがあれば配布ブランチを取り込み、そこへ `kovidgoyal/kitty` の `master` を merge する。fork のコミットと upstream の履歴を保持する。
3. `flake.lock` の Nixpkgs pin と Go vendor hash を更新する。
4. 更新ツールのテスト、両Linuxアーキテクチャの評価、x86_64 の sandbox ビルド＋回帰テストを実行する。
5. 成功した候補だけを通常の push で公開し、更新PRを作成／再利用する。
6. PR側の必須CI成功を待つ auto-merge（merge commit）を要求する。

配布ブランチへの直接 push、rebase、force push は行わない。競合、依存 hash 取得失敗、ビルド失敗時は公開・マージしない。GitHub の workflow failure 通知を有効にすること。競合解消の自動推測はしない。

### GitHub 側の必須設定

この作業では GitHub に push したり設定したりしていない。公開後に管理者が以下を設定する:

1. fork の Actions を有効化する。fork では scheduled workflow が初期状態で停止している場合がある。
2. Repository settings の **Allow auto-merge** と **merge commits** を有効化する。
3. default branch に通常の **branch protection rule** を設定し、**Nix package and regression tests** を required status check にし、**Require branches to be up to date before merging** も有効化する。チェックを選べない場合は先に `Soft fork Nix` を手動実行する。
4. required checks を bypass できない bot/token を使う。自動追従PR以外も保護するため、必要なら直接 push も制限する。
5. `UPSTREAM_SYNC_TOKEN` という Actions secret を登録する。この fork だけに限定した fine-grained PAT に **Contents: read/write**, **Pull requests: read/write**, **Workflows: read/write**, **Administration: read** を付与する。最後の権限は保護ルールの確認だけに使用する。classic PAT を使う場合は `repo` と `workflow` scope が必要。
6. `Soft fork weekly upstream sync` を手動実行して初回を確認する。

同期workflowは auto-merge と required check の設定をAPIで確認し、不備があれば処理を開始せず失敗する。現実装の検査は通常の branch protection API を使用するため、**ruleset のみの保護は対象外**。必要なら通常の保護ルールを併用する。

通常の `GITHUB_TOKEN` による push/PR では後続のCIイベントが起動しないため、PATを明示的に要求する。トークンは fork の管理者が登録し、リポジトリには保存しない。GitHub App の導入は未実装。

`soft-fork-nix.yml` は push / pull_request / 手動実行で動作する。GitHub-hosted x86_64 runner 上で実パッケージをビルドする。aarch64 は評価のみで、native ビルド・GPU画面検証は行わない。既存の upstream workflows は削除・変更していないため、それらも実行される。

週次追従はこの fork を更新するだけで、利用側の NixOS/HM flake.lock を更新するものではない。利用側では `nix flake update kitty-soft-fork` と rebuild を行う。

## 保守・手動検証

```sh
python3 -m unittest discover -s nix/tests -v
nix flake check --all-systems --no-build
nix build --no-link -L .#checks.x86_64-linux.package
python3 nix/update-go-deps.py --check
# Go 依存を変更した場合:
python3 nix/update-go-deps.py
```

hash 更新は既知の固定出力 hash mismatch だけを採用し、ネットワーク障害やその他のエラーから hash を推測しない。更新後の再ビルドにも失敗した場合は元の hash ファイルへ戻す。

`nix/sync-upstream.sh` は **CI の使い捨て checkout** 用。ローカルで試す場合は新しい clone を使うこと。dirty checkout は拒否するが、専用のローカル作業ブランチはリモートの状態へリセットする。`BASE_BRANCH` / `SYNC_BRANCH` / `UPSTREAM_URL` / `UPSTREAM_BRANCH` を環境変数で指定できる。スクリプト単独では dependency refresh、push、PR作成を行わない。

手動の実 niri / RGBA テストは `docs/background-opacity-all-colors.md` と `kitty_tests/manual_background_opacity.py` を参照。
