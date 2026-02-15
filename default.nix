{
  buildPythonPackage,
  lib,
  pytestCheckHook,
  pytest-asyncio,
  aiohttp,
  matrix-nio,
  python-dotenv,
  setproctitle,
  setuptools,
}:
buildPythonPackage {
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
    pytestCheckHook
    pytest-asyncio
  ];

  pythonImportsCheck = [ "paca_matrix" ];

  meta = {
    mainProgram = "paca";
    # description = "A short description of my application";
    # homepage = "https://github.com";
    # license = lib.licenses.mit;
  };
}
