# tests/test_etl_transform.py
import json

import pytest
from etl_service.transform import (
    TransformBusyError,
    TransformRunner,
    build_dbt_args,
    summarize_run_results,
    validate_select,
)

from shared.config import Settings

RUN_RESULTS = {
    "elapsed_time": 12.5,
    "results": [
        {"unique_id": "model.taxi_platform.fct_trips", "status": "success"},
        {"unique_id": "seed.taxi_platform.vendors", "status": "success"},
        {
            "unique_id": "test.taxi_platform.unique_fct_trips_trip_id",
            "status": "fail",
            "message": "Got 3 results, configured to fail if != 0",
            "failures": 3,
        },
    ],
}


def test_validate_select_accepts_normal_selectors():
    assert validate_select("fct_trips+") == "fct_trips+"
    assert validate_select("tag:marts dim_zone") == "tag:marts dim_zone"


@pytest.mark.parametrize("bad", ["--target prod", "; rm -rf /", "", "a|b", "-x"])
def test_validate_select_rejects_anything_that_looks_like_an_option_or_a_command(bad):
    with pytest.raises(ValueError):
        validate_select(bad)


def test_build_args_for_a_full_refresh_with_selector():
    args = build_dbt_args("build", "/app/dbt", select="fct_trips+ dim_zone", full_refresh=True)
    assert args[:3] == ["dbt", "--no-use-colors", "build"]
    assert args[args.index("--select") + 1 :][:2] == ["fct_trips+", "dim_zone"]
    assert "--full-refresh" in args


def test_test_command_never_gets_full_refresh():
    assert "--full-refresh" not in build_dbt_args("test", "/app/dbt", full_refresh=True)


def test_unknown_command_is_rejected():
    with pytest.raises(ValueError):
        build_dbt_args("run-operation", "/app/dbt")


def test_summarize_run_results_counts_and_lists_problems():
    summary = summarize_run_results(RUN_RESULTS)
    assert summary["total"] == 3
    assert summary["counts"] == {"success": 2, "fail": 1}
    assert [problem["status"] for problem in summary["problems"]] == ["fail"]
    assert summary["problems"][0]["failures"] == 3


@pytest.fixture
def runner(tmp_path):
    return TransformRunner(Settings(_env_file=None, dbt_project_dir=str(tmp_path)))


def test_run_reads_results_written_by_dbt(runner, tmp_path, monkeypatch):
    def fake_execute(args):
        (tmp_path / "target").mkdir(exist_ok=True)
        (tmp_path / "target" / "run_results.json").write_text(json.dumps(RUN_RESULTS))
        return 1, "line1\nline2"

    monkeypatch.setattr(runner, "_execute", fake_execute)

    result = runner.run("build")

    assert result["success"] is False  # return code 1
    assert result["results"]["counts"]["fail"] == 1
    assert result["log_tail"] == ["line1", "line2"]
    assert runner.last_run()["command"] == "build"


def test_stale_results_from_an_earlier_run_are_ignored(runner, tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    old = target / "run_results.json"
    old.write_text(json.dumps(RUN_RESULTS))
    import os

    os.utime(old, (1, 1))  # pretend it is ancient
    monkeypatch.setattr(runner, "_execute", lambda args: (2, "dbt crashed before writing results"))

    result = runner.run("build")

    assert result["results"] is None


def test_second_run_while_busy_is_refused(runner):
    runner._lock.acquire()
    with pytest.raises(TransformBusyError):
        runner.run("build")
