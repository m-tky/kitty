{
  description = "kitty soft fork: unlimited translucent cell background colors";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      overlay = final: prev: {
        kitty-soft-fork = final.callPackage ./nix/package.nix {
          source = self;
        };
      };
      pkgsFor =
        system:
        import nixpkgs {
          inherit system;
          overlays = [ overlay ];
        };
    in
    {
      overlays.default = overlay;
      packages = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          default = pkgs.kitty-soft-fork;
          kitty = pkgs.kitty-soft-fork;
          go-modules = pkgs.kitty-soft-fork.goModules;
        }
      );
      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${system}.kitty;
        };
        kitty = self.apps.${system}.default;
      });
      checks = forAllSystems (system: {
        package = self.packages.${system}.kitty;
      });
      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          default = pkgs.mkShell {
            inputsFrom = [ self.packages.${system}.kitty ];
            packages = [
              pkgs.git
              pkgs.nixfmt
              pkgs.ruff
              pkgs.clang-tools
            ];
          };
        }
      );
      nixosModules.default =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          cfg = config.programs.kitty-soft-fork;
        in
        {
          options.programs.kitty-soft-fork = {
            enable = lib.mkEnableOption "the kitty soft fork";
            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.kitty;
              description = "kitty soft-fork package to install system-wide.";
            };
          };
          config = lib.mkIf cfg.enable {
            environment.systemPackages = [ cfg.package ];
          };
        };
      homeManagerModules.default = { lib, pkgs, ... }: {
        # Use Home Manager's existing kitty settings and enable option.
        programs.kitty.package = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.kitty;
      };
    };
}
