# tests/test_dashboard_flows.py
from pathlib import Path

import pytest

from dashboard_app import flows
from dashboard_app.flows import COLOR_CURRENT, COLOR_DONE, COLOR_PENDING

REPO_ROOT = Path(__file__).resolve().parents[1]


def line_for(dot: str, key: str) -> str:
    return next(line for line in dot.splitlines() if line.strip().startswith(f"{key} ["))


def test_the_flow_definitions_are_consistent():
    assert flows.problems() == []


def test_every_code_file_named_in_a_step_exists_in_the_repository():
    missing = [
        f"{flow.key} step {number}: {path}"
        for flow in flows.FLOWS
        for number, step in enumerate(flow.steps, start=1)
        for path in step.files
        if not (REPO_ROOT / path).exists()
    ]
    assert missing == []


def test_the_whole_path_is_drawn_in_one_colour_with_only_the_boxes_the_flow_uses():
    dot = flows.build_dot(flows.get_flow("upload"), 0)
    assert dot.startswith("digraph flow {")
    assert COLOR_CURRENT not in dot
    assert 't_upload -> ingestion [label="1", color="' + COLOR_DONE in dot
    assert "ingestion [" in dot
    assert "cleaning [" not in dot  # the upload flow never reaches the cleaning service


def test_a_step_highlights_its_arrow_marks_earlier_ones_done_and_later_ones_pending():
    dot = flows.build_dot(flows.get_flow("download"), 3)
    assert f'tlc -> ingestion [label="3", color="{COLOR_CURRENT}"' in dot
    assert f'ingestion -> registry [label="2, 5", color="{COLOR_DONE}"' in dot  # used in steps 2 and 5, first at 2
    assert f't_download -> ingestion [label="1", color="{COLOR_DONE}"' in dot
    pending = next(line for line in dot.splitlines() if "ingestion -> raw" in line)
    assert COLOR_PENDING in pending
    assert "style=dashed" in pending


def test_boxes_are_current_done_or_faded_following_the_step():
    dot = flows.build_dot(flows.get_flow("download"), 3)
    assert COLOR_CURRENT in line_for(dot, "tlc")  # in the current step
    assert 'fillcolor="#00000000"' in line_for(dot, "raw")  # only reached in a later step
    assert 'fillcolor="#00000000"' not in line_for(dot, "t_download")  # already done


def test_an_arrow_used_twice_carries_both_step_numbers():
    dot = flows.build_dot(flows.get_flow("download"), 0)
    assert 'ingestion -> registry [label="2, 5"' in dot


def test_the_final_step_without_arrows_shows_everything_as_done():
    flow = flows.get_flow("upload")
    assert flow.steps[-1].edges == ()
    dot = flows.build_dot(flow, len(flow.steps))
    assert COLOR_CURRENT not in dot.split("}\n")[-1]
    assert "style=dashed" not in "\n".join(line for line in dot.splitlines() if "->" in line)


def test_clusters_appear_only_when_they_contain_a_used_box():
    upload = flows.build_dot(flows.get_flow("upload"), 0)
    monitoring = flows.build_dot(flows.get_flow("monitoring"), 0)
    assert "cluster_lake" in upload
    assert "cluster_monitoring" not in upload
    assert "cluster_monitoring" in monitoring


def test_every_flow_can_be_drawn_at_every_step_with_balanced_braces():
    for flow in flows.FLOWS:
        for step in range(len(flow.steps) + 1):
            dot = flows.build_dot(flow, step)
            assert dot.count("{") == dot.count("}")


def test_a_step_outside_the_range_is_refused():
    flow = flows.get_flow("upload")
    with pytest.raises(ValueError):
        flows.build_dot(flow, len(flow.steps) + 1)
    with pytest.raises(ValueError):
        flows.build_dot(flow, -1)


def test_labels_are_escaped_for_graphviz():
    assert flows.quote_label('say "hi"\nnext') == 'say \\"hi\\"\\nnext'


def test_the_steps_table_has_one_row_per_step_with_code_files_in_backticks():
    flow = flows.get_flow("download")
    rows = flows.steps_table(flow).splitlines()
    assert rows[0].startswith("| Step |")
    assert len(rows) == 2 + len(flow.steps)
    assert "`services/ingestion/ingestion_service/downloader.py`" in rows[4]


def test_get_flow_rejects_unknown_keys():
    with pytest.raises(KeyError):
        flows.get_flow("nope")