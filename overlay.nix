final: prev: {
  python3 = prev.python3.override {
    packageOverrides = _: _: {
      paca-matrix = prev.python3.pkgs.callPackage ./default.nix { };
    };
  };

  python3Packages = final.python3.pkgs;

  paca-matrix = prev.python3.pkgs.toPythonApplication final.python3.pkgs.paca-matrix;
}
