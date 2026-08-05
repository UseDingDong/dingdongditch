from unittest.mock import MagicMock, patch

import pytest

from dingdongditch.cli import EXIT_INVALID_INPUT, EXIT_SUCCESS, build_parser, main


def test_profile_cli_lifecycle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DINGDONGDITCH_PROFILE_ROOT", str(tmp_path))
    assert main(["profile", "create", "work"]) == EXIT_SUCCESS
    assert main(["profile", "list"]) == EXIT_SUCCESS
    assert "profile=work" in capsys.readouterr().out
    assert main(["profile", "remove", "work"]) == EXIT_SUCCESS
    assert main(["profile", "remove", "work"]) == EXIT_INVALID_INPUT
    assert "profile_not_found" in capsys.readouterr().err


@pytest.mark.parametrize("profile_names", [[], ["one"], ["one", "two"]])
def test_profile_list_succeeds_for_zero_one_and_multiple_profiles(
    tmp_path, monkeypatch, capsys, profile_names
):
    monkeypatch.setenv("DINGDONGDITCH_PROFILE_ROOT", str(tmp_path))
    for name in profile_names:
        assert main(["profile", "create", name]) == EXIT_SUCCESS
    capsys.readouterr()

    assert main(["profile", "list"]) == EXIT_SUCCESS
    output = capsys.readouterr()
    assert output.err == ""
    assert [line.split()[0] for line in output.out.splitlines()] == [
        f"profile={name}" for name in profile_names
    ]


def test_profile_list_ignores_legacy_reserved_directory_without_name_validation(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DINGDONGDITCH_PROFILE_ROOT", str(tmp_path))
    (tmp_path / "dingdong").mkdir()
    assert main(["profile", "create", "named"]) == EXIT_SUCCESS
    capsys.readouterr()

    with patch(
        "dingdongditch.authentication.profiles.validate_profile_name",
        side_effect=AssertionError("list must not validate profile names"),
    ):
        assert main(["profile", "list"]) == EXIT_SUCCESS
    output = capsys.readouterr()
    assert output.err == ""
    assert "profile=named" in output.out
    assert "profile=dingdong" not in output.out


def test_session_cli_auto_starts_and_stops_profile():
    backend = MagicMock()
    with patch("dingdongditch.cli.PlaywrightBackend", return_value=backend):
        assert main(["session", "clear", "work"]) == EXIT_SUCCESS
    backend.start.assert_called_once_with()
    backend.authentication.clear_session.assert_called_once_with()
    backend.stop.assert_called_once_with()


def test_run_alias_accepts_profile_override(tmp_path):
    args = build_parser().parse_args(["run", str(tmp_path / "plan.json"), "--profile", "work"])
    assert args.command == "run"
    assert args.profile == "work"
