from py_start.lib import greet


def test_greet(capsys):
    greet("World")
    captured = capsys.readouterr()
    assert "Hello, World!" in captured.out
