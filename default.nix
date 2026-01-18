{
  python,
  buildPythonApplication,
  lib,
  python-dotenv,
  setuptools,
  pytest,
}:
buildPythonApplication {
  name = "paca-matrix";
  src = lib.cleanSource ./.;
  pyproject = true;

  nativeBuildInputs = [ setuptools ];

  propagatedBuildInputs = [
    python-dotenv
    python3Packages.matrix-nio
  ];

  nativeCheckInputs = [ pytest ];

  checkPhase = ''
    pytest
  '';

  pythonImportsCheck = [ "paca_matrix" ];

  passthru = {
    inherit python;
  };

  meta = {
    mainProgram = "paca";
    # description = "A short description of my application";
    # homepage = "https://github.com";
    # license = lib.licenses.mit;
  };
}
