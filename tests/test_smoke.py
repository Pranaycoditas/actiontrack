from typer.testing import CliRunner

from actiontrack.cli import app

runner = CliRunner()


def test_help_works():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("ingest", "list", "done", "followup"):
        assert command in result.output
