from unittest.mock import patch

from guandan.cli import main


def test_status_queries_and_invalid_input_do_not_consume_turn_budget(capsys):
    with patch("builtins.input", side_effect=["b", "invalid"] * 201 + ["q"]):
        assert main(["--first", "0", "--seed", "9"]) == 0
    assert "强制结束" not in capsys.readouterr().out


def test_eof_exits_cleanly(capsys):
    with patch("builtins.input", side_effect=EOFError):
        assert main(["--first", "0", "--seed", "9"]) == 0
    assert "已退出" in capsys.readouterr().out
