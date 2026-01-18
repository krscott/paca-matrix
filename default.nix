{
  python,
  buildPythonApplication,
  lib,
  python-dotenv,
  setuptools,
  pytest,
}:
buildPythonApplication {
  name = "py-start";
  src = lib.cleanSource ./.;
  pyproject = true;

  nativeBuildInputs = [ setuptools ];

  propagatedBuildInputs = [
    python-dotenv
  ];

  nativeCheckInputs = [ pytest ];

  checkPhase = ''
    pytest
  '';

  pythonImportsCheck = [ "py_start" ];

  passthru = {
    inherit python;
  };

  meta = {
    mainProgram = "pystart";
    # description = "A short description of my application";
    # homepage = "https://github.com";
    # license = lib.licenses.mit;
  };
}
