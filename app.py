"""Keystone demo UI."""
import streamlit as st
import pandas as pd
from graph_client import node_count, edge_count
from agent import run_keystone
from tools import explain_path

st.set_page_config(page_title="Keystone", layout="wide")

st.title("Keystone — knowledge-risk and reviewer routing")
st.caption("An agent that uses FalkorDB to decide and act on connected code data.")

with st.sidebar:
    st.header("Graph")
    st.metric("Nodes", node_count())
    st.metric("Edges", edge_count())

col1, col2 = st.columns([1, 3])
with col1:
    pr_number = st.number_input("PR number", min_value=1, value=13997, step=1)
with col2:
    question = st.text_input("Question", value="who should review this?")

if st.button("Investigate", type="primary"):
    with st.spinner("Running agent..."):
        try:
            st.session_state["result"] = run_keystone(pr_number, question)
        except Exception as e:
            st.error(f"Agent error: {type(e).__name__}: {e}")

result = st.session_state.get("result")
if not result:
    st.info("Enter a PR number and click Investigate.")
    st.stop()

st.subheader("Plan trace")
for line in result["trace"]:
    st.code(line, language=None)

st.subheader("Recommended reviewers")
reviewers = result["decision"]["reviewers"]
if reviewers:
    df = pd.DataFrame([
        {"login": r["login"], "score": round(r["score"], 3),
         "shared_files": r["shared_files"],
         "recent_reviews": r["recent_reviews"],
         "last_review": r["last_review"]}
        for r in reviewers
    ])
    st.dataframe(df, use_container_width=True)
else:
    st.warning("No reviewer above threshold.")

st.subheader("Risk flags")
flags = result["decision"]["risk_flags"]
if flags:
    for f in flags:
        st.error(f)
else:
    st.success("No risk flags.")

st.subheader("Proposed actions")
for i, a in enumerate(result["proposed_actions"]):
    with st.container(border=True):
        target = a.get("who") or a.get("label")
        st.write(f"**{a['action']}** — `{target}` on PR #{a['on']}")
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Approve", key=f"approve_{i}"):
            st.toast(f"Approved: {a['action']} {target} (stub — not executing)")
        if c2.button("Reject", key=f"reject_{i}"):
            st.toast(f"Rejected: {a['action']} {target}")

st.subheader("Explanation path")
if reviewers:
    top = reviewers[0]["login"]
    path = explain_path(pr_number, top)
    st.write(f"**{top}** was selected via {len(path.get('files', []))} shared file(s):")
    if path.get("files"):
        for f in path["files"][:10]:
            st.code(f"PR #{pr_number} -> {f} -> {top}", language=None)
    else:
        st.write("(no shared files found)")