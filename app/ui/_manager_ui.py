"""
Shared UI primitives for the two-panel (search + list / summary + editor)
manager pages: config_manager.py and schema_manager.py. Both pages track a
"working copy" of the selected object in st.session_state field-by-field
(one key per form widget) so the read-only summary and dirty-state check
can be recomputed live, on every rerun - not just at Save time (a plain
st.form batches widget changes until submit, which would make the summary
and dirty indicator go stale between keystrokes, so the editors deliberately
use plain widgets instead).

Nothing here talks to a service or a store - purely rendering + session_state
bookkeeping shared by both pages.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import streamlit as st


def is_dirty(current: Dict[str, Any], original: Dict[str, Any]) -> bool:
    return current != original


def render_list_row(
    title: str,
    subtitle: str,
    caption: str,
    is_selected: bool,
    button_key: str,
) -> bool:
    """Renders one bordered row in the left-panel list. Returns True if its
    Open button was clicked this run."""
    with st.container(border=True):
        cols = st.columns([4, 1])
        with cols[0]:
            st.markdown(f"{'🟢 ' if is_selected else ''}**{title}**")
            st.caption(subtitle)
            if caption:
                st.caption(caption)
        with cols[1]:
            label = "Selected" if is_selected else "Open"
            return cols[1].button(
                label, key=button_key, use_container_width=True,
                disabled=is_selected, type="secondary",
            )
    return False


def show_unsaved_changes_dialog(
    on_save: Callable[[], None],
    on_discard: Callable[[], None],
    on_cancel: Callable[[], None],
) -> None:
    """Renders the "You have unsaved changes" modal (Save / Discard /
    Cancel) required before switching selection while the working copy
    differs from the loaded object."""

    @st.dialog("Unsaved changes")
    def _dialog():
        st.write("You have unsaved changes.")
        c1, c2, c3 = st.columns(3)
        if c1.button("💾 Save", use_container_width=True, type="primary", key="ucd_save"):
            on_save()
        if c2.button("🗑️ Discard", use_container_width=True, key="ucd_discard"):
            on_discard()
        if c3.button("✖ Cancel", use_container_width=True, key="ucd_cancel"):
            on_cancel()

    _dialog()


def text_to_list(text: str) -> list:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def list_to_text(items) -> str:
    return ", ".join(items or [])
