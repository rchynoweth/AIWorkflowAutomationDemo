"""Demo Story: the guided storyline with talk track for presenters."""
from __future__ import annotations

import streamlit as st

from app.components.styles import esc
from app.components.talk_track import chapter_note, go_to_chapter, story

PAGE_LABELS = {"home": "Home", "priority_queue": "Priority Queue", "loan_360": "Loan 360", "portfolio": "Portfolio",
               "agent_activity": "Agent Activity", "agent": "Meet the Agent", "evaluation": "Evaluation", "how_it_works": "How It Works"}


def render() -> None:
    s = story()["story"]
    st.markdown(f"## {esc(s['title'])}")
    st.markdown(f'<div class="lsi-rule" style="font-size:1.05rem">{esc(s["promise"])}</div>', unsafe_allow_html=True)
    total = sum(c.get("minutes", 0) for c in s["chapters"])
    st.caption(f"{len(s['chapters'])} chapters · about {total} minutes · every chapter opens the right page "
               "(and loan) with its talk track at the top. Toggle presenter notes in the sidebar.")

    done = st.session_state.setdefault("story_done", set())
    for i, chapter in enumerate(s["chapters"], 1):
        with st.container(border=True):
            left, right = st.columns([5, 1])
            loan = f" · `{chapter['loan_id']}`" if chapter.get("loan_id") else ""
            check = "(done) " if chapter["id"] in done else ""
            left.markdown(f"**{check}{i}. {esc(chapter['title'])}** &nbsp; "
                          f"<span style='color:#667085'>{PAGE_LABELS[chapter['page']]}{loan} · "
                          f"{chapter.get('minutes', 1)} min</span><br>{esc(chapter['goal'])}",
                          unsafe_allow_html=True)
            if right.button("Open", key=f"open_{chapter['id']}", use_container_width=True, type="primary"):
                done.add(chapter["id"])
                go_to_chapter(chapter)
            with left.expander("Talk track"):
                chapter_note(chapter)
    if st.button("Reset story progress"):
        st.session_state["story_done"] = set()
        st.session_state.pop("story_chapter", None)
        st.rerun()
