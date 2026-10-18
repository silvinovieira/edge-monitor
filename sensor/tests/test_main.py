import pytest

from sensor.__main__ import main


def _rows(output: str) -> list[list[str]]:
    return [line.split(",") for line in output.strip().splitlines()]


def test_writes_header_and_one_row_per_sample(capsys):
    main(["--seconds", "0.5"])
    rows = _rows(capsys.readouterr().out)
    assert rows[0] == ["t", "accel", "in_fault"]
    assert len(rows) == 1 + 500
    assert rows[1][0] == "0.000" and rows[-1][0] == "0.499"


def test_fault_flag_follows_the_configured_window(capsys, monkeypatch):
    monkeypatch.setenv("SENSOR_FAULT_START", "0.2")
    monkeypatch.setenv("SENSOR_FAULT_DURATION", "0.1")
    main(["--seconds", "0.5"])
    flagged = [row[0] for row in _rows(capsys.readouterr().out)[1:] if row[2] == "1"]
    assert flagged[0] == "0.200" and flagged[-1] == "0.299" and len(flagged) == 100


def test_no_fault_never_flags(capsys, monkeypatch):
    monkeypatch.setenv("SENSOR_FAULT_START", "0")
    main(["--seconds", "0.5", "--no-fault"])
    assert all(row[2] == "0" for row in _rows(capsys.readouterr().out)[1:])


def test_rejects_non_positive_seconds():
    with pytest.raises(SystemExit):
        main(["--seconds", "0"])
