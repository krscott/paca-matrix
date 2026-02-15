{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
    in
    flake-utils.lib.eachSystem supportedSystems (
      system:
      let
        localOverlay = import ./overlay.nix;

        pkgs = import nixpkgs {
          inherit system;
          overlays = [ localOverlay ];
        };

        pythonDev = pkgs.python3.pkgs.paca-matrix.pythonModule.withPackages (
          ps:
          with ps;
          [
            black
            isort
            mypy
            pytest
            pytest-asyncio
          ]
          ++ pkgs.python3.pkgs.paca-matrix.propagatedBuildInputs
          ++ pkgs.python3.pkgs.paca-matrix.nativeBuildInputs
        );

        mkApp = text: {
          type = "app";
          program = pkgs.lib.getExe (
            pkgs.writeShellApplication {
              name = "app";
              runtimeInputs = [ pythonDev ];
              inherit text;
            }
          );
        };
      in
      {
        packages = {
          inherit (pkgs) paca-matrix;
          default = pkgs.paca-matrix;
        };

        devShells = {
          default = pkgs.mkShell {
            inputsFrom = [ ];
            nativeBuildInputs = [
              pythonDev
              pkgs.pyright
            ];
            packages = [ pkgs.python3.pkgs.venvShellHook ];
            venvDir = ".venv";
            postVenvCreation = ''
              pip install -e '.[dev]'
            '';
            shellHook = ''
              runHook venvShellHook
              export PYTHONPATH="''${PYTHONPATH:-}:."
              if [ ! -f CLAUDE.md ]; then
                ln -s AGENTS.md CLAUDE.md
              fi
            '';
          };
        };

        apps = {
          format = mkApp ''
            ./format.sh
          '';

          mypy = mkApp ''
            mypy . "$@"
          '';

          pyright = mkApp ''
            pyright . "$@"
          '';
        };

        formatter = pkgs.nixfmt;
      }
    );
}
