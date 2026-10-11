"""Presenter talk-track notes (config/demo_story.yml), shown when presenter notes are on."""
from __future__ import annotations

from functools import lru_cache

import streamlit as st
import yaml

from app.components.styles import esc
from src.config.settings import repo_root


@lru_cache(maxsize=1)
def story() -> dict:
    with open(repo_root() / "config" / "demo_story.yml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def presenter_on() -> bool:
    return st.session_state.get("presenter_notes", True)


def notes(page_key: str) -> None:
    """Small talk-track callout for a page."""
    if not presenter_on():
        return
    page = story().get("page_notes", {}).get(page_key, {})
    lines, platform = page.get("story", []), page.get("databricks", [])
    if lines or platform:
        items = "".join(f"<li>{esc(line)}</li>" for line in lines)
        plat = "".join(f"<li>{esc(line)}</li>" for line in platform)
        st.markdown(f'<div class="lsi-talk"><b>Talk track</b><ul>{items}</ul>'
                    + (f'<b>On Databricks</b><ul>{plat}</ul>' if plat else "") + "</div>", unsafe_allow_html=True)


def chapter_note(chapter: dict) -> None:
    story_lines = "".join(f"<li>{esc(s)}</li>" for s in chapter.get("say", []))
    platform = "".join(f"<li>{esc(s)}</li>" for s in chapter.get("databricks", []))
    platform_block = (f'<div style="margin-top:6px"><b>On Databricks</b><ul>{platform}</ul></div>'
                      if platform else "")
    st.markdown(f'<div class="lsi-talk"><b>The story</b><ul>{story_lines}</ul>{platform_block}'
                f'<div style="margin-top:4px"><b>Do:</b> {esc(chapter.get("click", ""))}</div></div>',
                unsafe_allow_html=True)


def active_chapter_banner(page_key: str) -> None:
    """If the presenter launched a chapter for this page, show its notes at the top."""
    if not presenter_on():
        return
    chapter_id = st.session_state.get("story_chapter")
    chapter = next((c for c in story()["story"]["chapters"] if c["id"] == chapter_id), None)
    if chapter and chapter["page"] == page_key:
        chapters = story()["story"]["chapters"]
        idx = chapters.index(chapter)
        with st.container(border=True):
            st.markdown(f"**Chapter {idx + 1} of {len(chapters)} · {chapter['title']}** — {chapter['goal']}")
            chapter_note(chapter)
            if idx + 1 < len(chapters):
                nxt = chapters[idx + 1]
                if st.button(f"Next chapter: {nxt['title']} →", key=f"next_{chapter_id}"):
                    go_to_chapter(nxt)


def go_to_chapter(chapter: dict) -> None:
    from app.navigation import PAGES

    st.session_state["story_chapter"] = chapter["id"]
    if chapter.get("loan_id"):
        st.session_state["selected_loan_id"] = chapter["loan_id"]
    st.switch_page(PAGES[chapter["page"]])
