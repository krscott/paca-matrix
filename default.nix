{
  python,
  buildPythonApplication,
  lib,
  aiohttp,
  matrix-nio,
  pytest,
  pytest-asyncio,
  python-dotenv,
  setproctitle,
  setuptools,
}:
buildPythonApplication {
  name = "paca-matrix";
  src = lib.cleanSource ./.;
  pyproject = true;

  nativeBuildInputs = [ setuptools ];

  propagatedBuildInputs = [
    python-dotenv
    matrix-nio
    aiohttp
    setproctitle
  ];

  nativeCheckInputs = [
    pytest
    pytest-asyncio
  ];

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
