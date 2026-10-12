# services/dashboard/dashboard_app/flows.py
"""The data behind the "How it works" page: how work travels through the platform.

Each *flow* starts with a trigger (an upload, a download, a schedule...) and is a list of *steps*.
A step says what happens, which arrows light up in the diagram, and which code files to open.
`build_dot` turns a flow (and the step you are looking at) into a Graphviz drawing.

This module has no Streamlit code, so it is easy to test. To explain a new flow, add a `Flow` to `FLOWS`.
The tests check that every node exists and that every code file named here really exists in the repo.

How to read an arrow: it points the way the request or the data moves. "A -> B" means A sends a request or
data to B. For stores it means the reader follows the data (raw -> cleaning: cleaning reads the raw bucket).
"""

from dataclasses import dataclass

COLOR_CURRENT = "#d62728"  # the step you are looking at
COLOR_DONE = "#1f77b4"  # steps already walked through
COLOR_PENDING = "#8a8a8a"  # steps still to come


@dataclass(frozen=True)
class Node:
    """One box in the diagram.

    Attributes:
        key: Short identifier used in the steps' arrows.
        label: Text shown in the box ("\\n" starts a new line).
        kind: trigger, external, service, store or monitor (decides shape and colour).
        cluster: Group the box is drawn in, or None.
    """

    key: str
    label: str
    kind: str
    cluster: str | None = None


@dataclass(frozen=True)
class Step:
    """One step of a flow.

    Attributes:
        title: Short name of the step.
        text: Plain-English explanation.
        edges: Arrows that light up in this step, as (from_key, to_key) pairs.
        files: Code files to open to see this step happening.
    """

    title: str
    text: str
    edges: tuple[tuple[str, str], ...] = ()
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Flow:
    """A trigger and everything that follows from it.

    Attributes:
        key: Short identifier.
        title: Name shown in the selector.
        summary: One sentence describing the flow.
        steps: The steps, in order.
    """

    key: str
    title: str
    summary: str
    steps: tuple[Step, ...]


# ---- the boxes ----------------------------------------------------------------------
NODES: tuple[Node, ...] = (
    Node("t_upload", "You\nupload a file", "trigger"),
    Node("t_download", "You (or a script)\nask for a month", "trigger"),
    Node("t_drop", "You\ndrop a file in\ndata/dropzone", "trigger"),
    Node("t_schedule", "Time or a click\nschedule, backfill,\nmanual run", "trigger"),
    Node("t_view", "You\nopen the dashboard", "trigger"),
    Node("t_time", "Time passes\n(every 15 s and 5 min)", "trigger"),
    Node("tlc", "NYC TLC website\nmonthly Parquet files", "external"),
    Node("airflow", "Airflow\norchestrator", "service", "services"),
    Node("ingestion", "Ingestion\nservice", "service", "services"),
    Node("cleaning", "Cleaning\nservice", "service", "services"),
    Node("etl", "ETL service\nloader + dbt", "service", "services"),
    Node("quality", "Quality\nservice", "service", "services"),
    Node("analytics", "Analytics API\n(read-only)", "service", "services"),
    Node("dashboard", "Dashboard\n(Streamlit)", "service", "services"),
    Node("registry", "File registry\n(SQLite)", "store"),
    Node("raw", "bucket: raw\n(files as received)", "store", "lake"),
    Node("clean", "bucket: clean\n+ cleaning reports", "store", "lake"),
    Node("quarantine", "bucket: quarantine\n(rejected rows)", "store", "lake"),
    Node("landing", "landing.trips", "store", "warehouse"),
    Node("star", "analytics schema\nstar schema + summaries", "store", "warehouse"),
    Node("prometheus", "Prometheus\n(collects metrics)", "monitor", "monitoring"),
    Node("grafana", "Grafana\n(dashboards)", "monitor", "monitoring"),
)
NODE_BY_KEY = {node.key: node for node in NODES}

CLUSTERS = {
    "services": "Services",
    "lake": "Object storage (data lake)",
    "warehouse": "Warehouse (PostgreSQL)",
    "monitoring": "Monitoring",
}

# kind -> (Graphviz shape, fill colour)
KIND_STYLE = {
    "trigger": ("ellipse", "#FFD8A8"),
    "external": ("component", "#E0E0E0"),
    "service": ("box", "#B7D4FF"),
    "store": ("cylinder", "#BFE8BF"),
    "monitor": ("box", "#DCC7F5"),
}

# ---- the flows -----------------------------------------------------------------------
_INGEST = "services/ingestion/ingestion_service"
_CLEAN = "services/cleaning/cleaning_service"
_ETL = "services/etl/etl_service"
_QUALITY = "services/quality/quality_service"
_AIRFLOW = "airflow/dags"

FLOWS: tuple[Flow, ...] = (
    Flow(
        key="upload",
        title="Upload a file through the API",
        summary="You hand the platform a data file; it checks it and stores it, untouched, as raw data.",
        steps=(
            Step(
                "You send a file",
                "You pick a Parquet, CSV or JSON-lines file on the ingestion service's Swagger page (or send it from a "
                "script). The service saves it to a temporary spot first so it can inspect it.",
                (("t_upload", "ingestion"),),
                (f"{_INGEST}/routes.py",),
            ),
            Step(
                "Have we seen this file before?",
                "It computes a fingerprint (SHA-256) of the content and asks the file registry. The same fingerprint "
                "means a duplicate: the answer is 'duplicate' and nothing else happens. File types we do not accept "
                "are refused (HTTP 415) and unreadable files are refused too (HTTP 422).",
                (("ingestion", "registry"),),
                (f"{_INGEST}/ingest.py", f"{_INGEST}/file_utils.py", f"{_INGEST}/registry.py"),
            ),
            Step(
                "The untouched file goes into the raw bucket",
                "Files named like official TLC files are filed under yellow_tripdata/year=YYYY/month=MM/, the zone "
                "lookup goes under reference/, anything else under uploads/. The file is never edited: raw data stays "
                "exactly as received.",
                (("ingestion", "raw"),),
                (f"{_INGEST}/ingest.py", "shared/storage.py"),
            ),
            Step(
                "It writes down what it stored",
                "Name, size, fingerprint, row count, source and time go into the registry. This is the audit trail, and "
                "it is how other services learn which file belongs to which month, by asking the ingestion API.",
                (("ingestion", "registry"),),
                (f"{_INGEST}/registry.py",),
            ),
            Step(
                "Done: raw data is waiting",
                "Nothing has been cleaned yet. Cleaning, loading and modelling are separate steps; see the Airflow flow.",
            ),
        ),
    ),
    Flow(
        key="download",
        title="Download a month from the TLC website",
        summary="Someone asks for a month; the ingestion service fetches it from NYC TLC and stores it as raw data.",
        steps=(
            Step(
                "Someone asks for a month",
                "You call POST /ingest/trips/download with a month such as 2024-01, from the Swagger page or a script "
                "(Airflow makes the same call in its pipeline). A range of months is handled one month at a time, and one "
                "bad month never stops the others.",
                (("t_download", "ingestion"),),
                (f"{_INGEST}/routes.py",),
            ),
            Step(
                "Do we already have this month?",
                "The registry is checked by year and month. If the month is there, the answer is 'skipped' and nothing is "
                "downloaded, which is why asking twice is harmless.",
                (("ingestion", "registry"),),
                (f"{_INGEST}/ingest.py", f"{_INGEST}/registry.py"),
            ),
            Step(
                "Download from TLC",
                "The Parquet file is streamed to disk in chunks. Temporary errors are retried with growing waits. "
                "'Not published yet' (HTTP 403 or 404) is reported as 'not_available' without retrying, because waiting "
                "will not help.",
                (("tlc", "ingestion"),),
                (f"{_INGEST}/downloader.py",),
            ),
            Step(
                "Check it and store it",
                "The same steps as an upload: fingerprint, check the file is readable, count its rows, then store it "
                "untouched in the raw bucket.",
                (("ingestion", "raw"),),
                (f"{_INGEST}/ingest.py", f"{_INGEST}/file_utils.py", "shared/storage.py"),
            ),
            Step(
                "Record it",
                "The registry gets a new line: name, size, fingerprint, row count, month and source.",
                (("ingestion", "registry"),),
                (f"{_INGEST}/registry.py",),
            ),
            Step(
                "Done: the month is raw data",
                "The file is in the raw bucket and in the registry. Cleaning is the next step (see the Airflow flow).",
            ),
        ),
    ),
    Flow(
        key="dropzone",
        title="Drop a file into the drop folder",
        summary="Copy a file into data/dropzone on your machine; the ingestion service picks it up by itself.",
        steps=(
            Step(
                "The service notices the file",
                "A background task looks at the data/dropzone folder every 10 seconds. A file changed in the last two "
                "seconds is skipped, because it may still be copying.",
                (("t_drop", "ingestion"),),
                (f"{_INGEST}/dropzone.py", f"{_INGEST}/main.py"),
            ),
            Step(
                "Have we seen this file before?",
                "Same rule as everywhere: fingerprint it and ask the registry. Duplicates are not stored twice.",
                (("ingestion", "registry"),),
                (f"{_INGEST}/ingest.py", f"{_INGEST}/registry.py"),
            ),
            Step(
                "The untouched file goes into the raw bucket",
                "The file is checked and stored exactly as it is. The folder it goes to depends on its name.",
                (("ingestion", "raw"),),
                (f"{_INGEST}/ingest.py", "shared/storage.py"),
            ),
            Step(
                "It writes down what it stored",
                "The registry records the file, with source 'dropzone'.",
                (("ingestion", "registry"),),
                (f"{_INGEST}/registry.py",),
            ),
            Step(
                "The file is moved aside",
                "On success it moves to data/dropzone/processed/. Unsupported or corrupt files move to "
                "data/dropzone/failed/. The folder therefore only ever shows what is still waiting.",
                (("ingestion", "t_drop"),),
                (f"{_INGEST}/dropzone.py",),
            ),
            Step(
                "Done: raw data is waiting",
                "As with every way in, the data is now raw. Cleaning and the rest are run by the pipeline.",
            ),
        ),
    ),
    Flow(
        key="pipeline",
        title="A scheduled or backfilled Airflow run (the full pipeline)",
        summary="Airflow takes one month from the TLC website all the way to the warehouse, calling each service in order.",
        steps=(
            Step(
                "A run is created for a month",
                "Airflow creates a run on the monthly schedule, from a Trigger click (with a month parameter), or from a "
                "backfill over past months. The month comes from the run's logical date; scheduled runs go back a "
                "couple of months because TLC publishes late.",
                (("t_schedule", "airflow"),),
                (f"{_AIRFLOW}/taxi_month_pipeline.py", f"{_AIRFLOW}/taxi_pipeline/months.py"),
            ),
            Step(
                "Are all services ready?",
                "The first task asks each service's readiness endpoint and fails early, naming the service, if one is down.",
                (("airflow", "ingestion"), ("airflow", "cleaning"), ("airflow", "etl")),
                (f"{_AIRFLOW}/taxi_pipeline/services.py",),
            ),
            Step(
                "Ingest the month",
                "Airflow calls the ingestion service, which does exactly what the download flow shows. If TLC has not "
                "published the month yet the task is skipped, and so is everything after it. The zone lookup table is "
                "ingested and loaded alongside.",
                (("airflow", "ingestion"), ("tlc", "ingestion"), ("ingestion", "raw"), ("ingestion", "registry")),
                (f"{_AIRFLOW}/taxi_month_pipeline.py", f"{_INGEST}/ingest.py"),
            ),
            Step(
                "Clean the month",
                "The cleaning service asks the ingestion API where the month's file is (it never opens the registry "
                "itself), reads it from raw and applies the rules in DuckDB. Good rows go to the clean bucket, rejected "
                "rows go to quarantine with the reasons. It then checks its own output against a data contract, "
                "reconciles the row counts, and only then publishes, writing the cleaning report last.",
                (
                    ("airflow", "cleaning"),
                    ("cleaning", "ingestion"),
                    ("raw", "cleaning"),
                    ("cleaning", "clean"),
                    ("cleaning", "quarantine"),
                ),
                (f"{_CLEAN}/cleaner.py", f"{_CLEAN}/rules.py", f"{_CLEAN}/engine.py", f"{_CLEAN}/contract.py"),
            ),
            Step(
                "Load into the warehouse",
                "The ETL service reads the clean file, converts it to CSV and bulk-loads it into landing.trips with "
                "PostgreSQL COPY. Deleting the month's old rows, loading and counting happen in one transaction: all or "
                "nothing.",
                (("airflow", "etl"), ("clean", "etl"), ("etl", "landing")),
                (f"{_ETL}/loader.py", f"{_ETL}/export.py", f"{_ETL}/warehouse.py"),
            ),
            Step(
                "Build the star schema with dbt",
                "dbt reads landing.trips and builds the staging views, the dimension tables, the incremental fact table "
                "fct_trips and the summary tables the dashboard uses. Its tests run in the same step; a failing test "
                "fails the run.",
                (("airflow", "etl"), ("landing", "etl"), ("etl", "star")),
                (f"{_ETL}/transform.py", "dbt/models/marts/fct_trips.sql", "dbt/models/marts/trip_summary.sql"),
            ),
            Step(
                "Cross-check the stages",
                "Airflow asks the cleaning service how many rows it published and the ETL service how many it loaded. "
                "The two numbers must match.",
                (("airflow", "cleaning"), ("airflow", "etl")),
                (f"{_AIRFLOW}/taxi_pipeline/services.py",),
            ),
            Step(
                "Run the quality gate",
                "The quality service runs its six checks on the warehouse and the cleaning reports. Any failing check "
                "fails the Airflow run, so bad data cannot slip through quietly.",
                (("airflow", "quality"), ("landing", "quality"), ("star", "quality")),
                (f"{_QUALITY}/monitor.py", f"{_QUALITY}/checks.py"),
            ),
            Step(
                "Done: the month is ready",
                "All tasks are green: the month is in the warehouse and shows up in the dashboard (after the five-minute "
                "cache, or when you press Refresh data).",
            ),
        ),
    ),
    Flow(
        key="dashboard",
        title="Open the dashboard",
        summary="You look at the data; the dashboard never touches the database, it asks the analytics API.",
        steps=(
            Step(
                "You open the page",
                "Streamlit runs the page script from top to bottom, and again every time you change a filter.",
                (("t_view", "dashboard"),),
                ("services/dashboard/dashboard_app/app.py",),
            ),
            Step(
                "The page asks the analytics API",
                "The dashboard has no database access. It sends HTTP requests carrying your filters (dates, borough, "
                "payment type). Answers are remembered for five minutes, so moving around feels instant.",
                (("dashboard", "analytics"),),
                ("services/dashboard/dashboard_app/api_client.py",),
            ),
            Step(
                "The API queries small summary tables",
                "It runs read-only SQL (values passed as parameters, never pasted in) on trip_summary and route_summary, "
                "which dbt built in advance. They store sums, so averages stay correct whatever you filter. A 30-second "
                "limit protects the database.",
                (("analytics", "star"),),
                (
                    "services/analytics/analytics_service/queries.py",
                    "services/analytics/analytics_service/database.py",
                    "dbt/models/marts/trip_summary.sql",
                ),
            ),
            Step(
                "The rows travel back",
                "The API turns rows into JSON with the averages worked out; the dashboard turns them into Plotly charts.",
                (("star", "analytics"), ("analytics", "dashboard")),
                ("services/analytics/analytics_service/routes.py", "services/dashboard/dashboard_app/charts.py"),
            ),
            Step(
                "You see the charts",
                "Change a filter and the flow repeats from step 2.",
                (("dashboard", "t_view"),),
                ("services/dashboard/dashboard_app/app.py",),
            ),
        ),
    ),
    Flow(
        key="monitoring",
        title="Time passes: monitoring and quality checks",
        summary="Nobody clicks anything. Metrics are collected every 15 seconds and the data is checked every 5 minutes.",
        steps=(
            Step(
                "Prometheus reads every service",
                "Every 15 seconds Prometheus reads each service's /metrics page: request counts and timings, plus pipeline "
                "numbers such as rows cleaned and rows quarantined.",
                (
                    ("t_time", "prometheus"),
                    ("ingestion", "prometheus"),
                    ("cleaning", "prometheus"),
                    ("etl", "prometheus"),
                    ("analytics", "prometheus"),
                    ("quality", "prometheus"),
                ),
                ("shared/observability.py", "monitoring/prometheus/prometheus.yml"),
            ),
            Step(
                "The quality service checks the data",
                "Every 5 minutes it looks at the warehouse and asks the cleaning and ETL services for their reports and "
                "the last dbt run. It runs six checks: freshness, row counts, quarantine rate, schema drift, row "
                "reconciliation and the dbt result.",
                (
                    ("t_time", "quality"),
                    ("landing", "quality"),
                    ("star", "quality"),
                    ("cleaning", "quality"),
                    ("etl", "quality"),
                ),
                (f"{_QUALITY}/monitor.py", f"{_QUALITY}/checks.py", f"{_QUALITY}/sources.py"),
            ),
            Step(
                "The results become metrics",
                "Each check's verdict is published as a number (0 fail, 1 warn, 2 ok) on the quality service's own "
                "/metrics page, so Prometheus collects it like everything else.",
                (("quality", "prometheus"),),
                (f"{_QUALITY}/metrics.py",),
            ),
            Step(
                "Rules and dashboards",
                "Prometheus evaluates the alert rules (service down, failing check, high quarantine rate, failing dbt "
                "run...) and Grafana draws the Pipeline health dashboard from the same data.",
                (("prometheus", "grafana"),),
                ("monitoring/prometheus/alerts.yml", "monitoring/grafana/dashboards/pipeline-health.json"),
            ),
            Step(
                "A human looks",
                "Alerts are visible in Prometheus and Grafana. Nobody is notified automatically yet; that comes with "
                "deployment (Milestone 8).",
            ),
        ),
    ),
)


def get_flow(key: str) -> Flow:
    """Find a flow by its key.

    Args:
        key: The flow's key, for example "download".

    Returns:
        The flow.

    Raises:
        KeyError: If there is no such flow.
    """
    for flow in FLOWS:
        if flow.key == key:
            return flow
    raise KeyError(key)


def edge_usage(flow: Flow) -> dict[tuple[str, str], list[int]]:
    """List, for every arrow of a flow, the steps it is used in.

    Args:
        flow: The flow.

    Returns:
        {(from, to): [step numbers]}, with arrows in the order they first appear.
    """
    usage: dict[tuple[str, str], list[int]] = {}
    for number, step in enumerate(flow.steps, start=1):
        for pair in step.edges:
            numbers = usage.setdefault(pair, [])
            if number not in numbers:
                numbers.append(number)
    return usage


def flow_nodes(flow: Flow) -> list[str]:
    """The boxes a flow touches, in a fixed order.

    Args:
        flow: The flow.

    Returns:
        Node keys.
    """
    touched = {key for pair in edge_usage(flow) for key in pair}
    return [node.key for node in NODES if node.key in touched]


def quote_label(text: str) -> str:
    """Make text safe inside a double-quoted Graphviz label.

    Args:
        text: Label text; newlines become line breaks in the box.

    Returns:
        The escaped text.
    """
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _node_line(node: Node, state: str) -> str:
    """One Graphviz line for a box. `state` is current, done or faded."""
    shape, fill = KIND_STYLE[node.kind]
    label = quote_label(node.label)
    if state == "faded":
        style = (
            f'shape={shape}, style="filled,dashed", fillcolor="#00000000", color="{COLOR_PENDING}", '
            f'fontcolor="{COLOR_PENDING}"'
        )
    else:
        border = COLOR_CURRENT if state == "current" else "#555555"
        width = 3 if state == "current" else 1.2
        style = f'shape={shape}, style=filled, fillcolor="{fill}", color="{border}", penwidth={width}, fontcolor="#111111"'
    return f'{node.key} [label="{label}", {style}];'


def build_dot(flow: Flow, step: int = 0) -> str:
    """Draw a flow as Graphviz (DOT) text.

    Only the boxes the flow uses are drawn. Step 0 shows the whole path. For step n, the arrows of step n are
    red and thick, arrows of earlier steps are blue, and arrows still to come are grey and dashed.

    Args:
        flow: The flow to draw.
        step: 0 for the whole path, otherwise the 1-based step to highlight.

    Returns:
        DOT source for `st.graphviz_chart`.

    Raises:
        ValueError: If `step` is outside 0..number of steps.
    """
    if not 0 <= step <= len(flow.steps):
        raise ValueError(f"step must be between 0 and {len(flow.steps)}")

    usage = edge_usage(flow)
    current_edges = set(flow.steps[step - 1].edges) if step else set()
    done_nodes: set[str] = set()
    current_nodes: set[str] = set()
    for number, item in enumerate(flow.steps, start=1):
        touched = {key for pair in item.edges for key in pair}
        if step == 0 or number < step:
            done_nodes |= touched
        elif number == step:
            current_nodes |= touched

    def node_state(key: str) -> str:
        if key in current_nodes:
            return "current"
        return "done" if key in done_nodes else "faded"

    def edge_state(pair: tuple[str, str], numbers: list[int]) -> str:
        if step == 0:
            return "done"
        if pair in current_edges:
            return "current"
        return "done" if min(numbers) < step else "pending"

    involved = flow_nodes(flow)
    lines = [
        "digraph flow {",
        '  rankdir=LR; bgcolor="transparent"; nodesep=0.4; ranksep=0.9;',
        '  node [fontname="Helvetica", fontsize=11, margin="0.15,0.08"];',
        '  edge [fontname="Helvetica", fontsize=11];',
    ]

    for cluster_key, title in CLUSTERS.items():
        members = [key for key in involved if NODE_BY_KEY[key].cluster == cluster_key]
        if not members:
            continue
        lines.append(
            f'  subgraph cluster_{cluster_key} {{ label="{quote_label(title)}"; style=dashed; '
            f'color="{COLOR_PENDING}"; fontcolor="{COLOR_PENDING}"; fontname="Helvetica"; fontsize=11;'
        )
        lines += [f"    {_node_line(NODE_BY_KEY[key], node_state(key))}" for key in members]
        lines.append("  }")

    lines += [f"  {_node_line(NODE_BY_KEY[key], node_state(key))}" for key in involved if NODE_BY_KEY[key].cluster is None]

    anchors = [key for key in involved if NODE_BY_KEY[key].kind in ("trigger", "external")]
    if anchors:
        lines.append("  { rank=min; " + "; ".join(anchors) + "; }")  # triggers on the left

    colors = {"current": COLOR_CURRENT, "done": COLOR_DONE, "pending": COLOR_PENDING}
    widths = {"current": 3.0, "done": 2.0, "pending": 1.2}
    for pair, numbers in usage.items():
        state = edge_state(pair, numbers)
        label = ", ".join(str(number) for number in numbers)
        style = "dashed" if state == "pending" else "solid"
        lines.append(
            f'  {pair[0]} -> {pair[1]} [label="{label}", color="{colors[state]}", fontcolor="{colors[state]}", '
            f"penwidth={widths[state]}, style={style}];"
        )

    lines.append("}")
    return "\n".join(lines)


def steps_table(flow: Flow) -> str:
    """The steps of a flow as a Markdown table.

    Args:
        flow: The flow.

    Returns:
        Markdown text with one row per step.
    """
    lines = ["| Step | What happens | Code to open |", "|---|---|---|"]
    for number, step in enumerate(flow.steps, start=1):
        code = ", ".join(f"`{path}`" for path in step.files) or "-"
        lines.append(f"| {number} | **{step.title}**: {step.text} | {code} |")
    return "\n".join(lines)


def problems() -> list[str]:
    """Check that the flow definitions are consistent (used by the tests).

    Returns:
        A list of problems; empty when everything is fine.
    """
    found: list[str] = []
    keys = [flow.key for flow in FLOWS]
    if len(keys) != len(set(keys)):
        found.append("duplicate flow keys")
    node_keys = [node.key for node in NODES]
    if len(node_keys) != len(set(node_keys)):
        found.append("duplicate node keys")
    for node in NODES:
        if node.kind not in KIND_STYLE:
            found.append(f"node {node.key}: unknown kind {node.kind}")
        if node.cluster is not None and node.cluster not in CLUSTERS:
            found.append(f"node {node.key}: unknown cluster {node.cluster}")
    for flow in FLOWS:
        if len(flow.steps) < 3:
            found.append(f"flow {flow.key}: needs at least 3 steps")
        for number, step in enumerate(flow.steps, start=1):
            where = f"flow {flow.key}, step {number}"
            if not step.title or not step.text:
                found.append(f"{where}: title and text are required")
            if any(char in step.title + step.text for char in ("|", "\n")):
                found.append(f"{where}: '|' and line breaks would break the Markdown table")
            for pair in step.edges:
                for key in pair:
                    if key not in NODE_BY_KEY:
                        found.append(f"{where}: unknown node '{key}'")
    return found
