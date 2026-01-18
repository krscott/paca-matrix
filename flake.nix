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
        pkgs = nixpkgs.legacyPackages.${system};

        # Final derivation including any overrides made to output package
        inherit (self.packages.${system}) py-start;

        pythonDev = py-start.python.withPackages (
          ps:
          with ps;
          [
            black
            isort
            mypy
          ]
          ++ py-start.propagatedBuildInputs
          ++ py-start.nativeBuildInputs
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
          default = py-start;

          py-start = pkgs.python3.pkgs.callPackage ./. { };

          py-start-test = py-start.override {
            doCheck = true;
          };
        };

        devShells = {
          default = pkgs.mkShell {
            inputsFrom = [ py-start ];
            nativeBuildInputs = [ pythonDev ];
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
        };

        formatter = pkgs.nixfmt;
      }
    );
}
