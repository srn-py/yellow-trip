# services/dashboard/dashboard_app/views/how_it_works.py
"""The "How it works" page: a guided tour of the platform, one trigger at a time.

This page is static explanation. Nothing here calls a service. Pick what starts the flow, then move the
Step slider to watch the work travel from service to service, with the code file to open at each step.
All content comes from `dashboard_app/flows.py`.
"""

import streamlit as st

from dashboard_app import flows

st.title("How the platform works")
st.write(
    "Pick what starts a flow, then move the **Step** slider to watch the work travel through the platform. "
    "Each step names the code file to open next."
)

with st.expander("Three ideas to keep in mind", expanded=False):
    st.markdown(
        "1. **Services only talk through APIs.** The cleaning service asks the ingestion API where a file is; it never "
        "opens the ingestion service's database.\n"
        "2. **Data moves through layers.** Raw files (exactly as received), then clean files plus a quarantine, then the "
        "warehouse tables that the dashboard reads.\n"
        "3. **Airflow only orchestrates.** It decides the order, timing and retries, and calls each service's API; it "
        "never touches data itself."
    )

st.markdown(
    "**Boxes:** 🟠 something that starts a flow &nbsp; 🔵 a service (its own container) &nbsp; "
    "🟢 storage (files or tables) &nbsp; ⚪ outside the platform &nbsp; 🟣 monitoring  \n"
    "**Arrows:** 🔴 the current step &nbsp; 🔷 steps already done &nbsp; ▫️ dashed grey: steps still to come. "
    "The numbers on an arrow are the steps that use it."
)

options = {flow.key: flow for flow in flows.FLOWS}
selected = st.selectbox(
    "What starts the flow?", options=list(options), format_func=lambda key: options[key].title
)
flow = options[selected]
st.markdown(f"**{flow.summary}**")

step = st.slider(
    "Step (0 shows the whole path)",
    min_value=0,
    max_value=len(flow.steps),
    value=0,
    key=f"step_{flow.key}",  # each flow remembers its own step
)

st.graphviz_chart(flows.build_dot(flow, step))

if step == 0:
    st.info("Move the slider to walk through the flow one step at a time.")
else:
    current = flow.steps[step - 1]
    st.subheader(f"Step {step} of {len(flow.steps)}: {current.title}")
    st.write(current.text)
    if current.files:
        st.markdown("**Open in the code:**")
        st.code("\n".join(current.files), language=None)

with st.expander("All steps of this flow"):
    st.markdown(flows.steps_table(flow))