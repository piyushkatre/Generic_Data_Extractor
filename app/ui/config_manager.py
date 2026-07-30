"""
Website Configuration Manager - search/list/create/edit/save-as/delete
WebsiteConfig, via ConfigService only (never ConfigStore directly).

Two-panel layout: a left search+list panel and a right summary+editor
panel that always shows the currently selected configuration (or "No
configuration selected"). The editor deliberately uses plain widgets, not
st.form - every widget has its own session_state key (cmf_<field>) so the
live summary and the dirty-state check (comparing the current session_state
values against the snapshot captured when this configuration was loaded)
recompute on every rerun, not just at Save time. See app/ui/_manager_ui.py
for the shared dirty-check/dialog/list-row helpers.

WebsiteConfig has no description/created_at/updated_at fields - those three
purely-presentational values live inside WebsiteConfig.metadata (an
existing free-form extensibility dict), exactly as before this rewrite.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from app.ui._services import get_config_service
from app.ui._errors import safe_call
from app.ui._manager_ui import is_dirty, render_list_row, show_unsaved_changes_dialog, text_to_list, list_to_text
from config.website_config import WebsiteConfig

st.set_page_config(page_title="Configuration Manager", page_icon="⚙️", layout="wide")
st.title("⚙️ Website Configuration Manager")

config_service = get_config_service()

FIELD_KEYS = [
    "name", "description", "domain", "priority",
    "wait_time_ms", "timeout_ms", "scroll_enabled", "max_scrolls", "infinite_scroll",
    "click_tabs_enabled", "click_tab_keywords",
    "remove_tags", "keep_tags", "allowed_attributes",
    "keywords", "ignore_sections",
]

st.session_state.setdefault("cm_selected_id", None)
st.session_state.setdefault("cm_loaded_config", None)
st.session_state.setdefault("cm_original_snapshot", None)
st.session_state.setdefault("cm_pending_selection", None)
st.session_state.setdefault("cm_show_unsaved_dialog", False)
st.session_state.setdefault("cm_confirm_delete", False)
st.session_state.setdefault("cm_save_as_open", False)
# Deferred-action markers: Save/Save As/Delete/Cancel Changes are rendered
# (and clicked) *after* the cmf_* widgets within the same script run, so
# they can't call _do_select()/_apply_snapshot_to_session_state() directly
# - Streamlit forbids writing to a widget-bound session_state key once that
# widget has already been instantiated this run. They set one of these
# markers instead and rerun; the marker is consumed at the very top of the
# next run, before any cmf_* widget exists yet.
st.session_state.setdefault("cm_pending_select_flag", False)
st.session_state.setdefault("cm_pending_select_target", None)
st.session_state.setdefault("cm_pending_reset_current", False)


# ---------------------------------------------------------------------------
# Snapshot <-> session_state <-> WebsiteConfig conversions
# ---------------------------------------------------------------------------

def _snapshot_from_config(config: WebsiteConfig, is_new: bool) -> Dict[str, Any]:
    meta = dict(config.metadata or {})
    wait_strategy = config.browser_config.get("wait_strategy", {})
    scroll_strategy = config.browser_config.get("scroll_strategy", {})
    lazy_loading = config.browser_config.get("lazy_loading", {})
    return {
        "name": "" if is_new else config.name,
        "description": meta.get("description", ""),
        "domain": config.domain,
        "priority": int(config.priority),
        "wait_time_ms": int(wait_strategy.get("wait_after_load_ms", 1000)),
        "timeout_ms": int(wait_strategy.get("timeout_ms", 30000)),
        "scroll_enabled": int(scroll_strategy.get("max_scrolls", 10)) > 0,
        "max_scrolls": int(scroll_strategy.get("max_scrolls", 10)) or 10,
        "infinite_scroll": bool(lazy_loading.get("enabled", True)),
        "click_tabs_enabled": bool(config.clickable_tabs.get("allowed_keywords") or config.clickable_tabs.get("selectors")),
        "click_tab_keywords": list_to_text(config.clickable_tabs.get("allowed_keywords", [])),
        "remove_tags": list_to_text(config.removable_elements.get("remove_tag_names", [])),
        "keep_tags": list_to_text(config.dom_clean_config.get("allowed_tags", [])),
        "allowed_attributes": list_to_text(config.dom_clean_config.get("allowed_attributes", [])),
        "keywords": list_to_text(config.keep_elements.get("keep_heading_keywords", [])),
        "ignore_sections": list_to_text(config.removable_elements.get("remove_heading_keywords", [])),
    }


def _apply_snapshot_to_session_state(snapshot: Dict[str, Any]) -> None:
    for key, value in snapshot.items():
        st.session_state[f"cmf_{key}"] = value


def _read_current_snapshot() -> Dict[str, Any]:
    return {key: st.session_state.get(f"cmf_{key}") for key in FIELD_KEYS}


def _build_payload(base_config: WebsiteConfig, snapshot: Dict[str, Any], name_override: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now().isoformat()
    meta = dict(base_config.metadata or {})
    meta["description"] = snapshot["description"]
    meta["created_at"] = meta.get("created_at") or now
    meta["updated_at"] = now

    wait_strategy = base_config.browser_config.get("wait_strategy", {})
    scroll_strategy = base_config.browser_config.get("scroll_strategy", {})
    lazy_loading = base_config.browser_config.get("lazy_loading", {})

    payload = base_config.to_dict()
    payload.update({
        "name": (name_override or snapshot["name"]).strip(),
        "domain": snapshot["domain"].strip() or "*",
        "priority": int(snapshot["priority"]),
        "metadata": meta,
        "browser_config": {
            **base_config.browser_config,
            "wait_strategy": {**wait_strategy, "wait_after_load_ms": int(snapshot["wait_time_ms"]), "timeout_ms": int(snapshot["timeout_ms"])},
            "scroll_strategy": {**scroll_strategy, "max_scrolls": int(snapshot["max_scrolls"]) if snapshot["scroll_enabled"] else 0},
            "lazy_loading": {**lazy_loading, "enabled": snapshot["infinite_scroll"]},
        },
        "clickable_tabs": {
            **base_config.clickable_tabs,
            "allowed_keywords": text_to_list(snapshot["click_tab_keywords"]) if snapshot["click_tabs_enabled"] else [],
        },
        "removable_elements": {
            **base_config.removable_elements,
            "remove_tag_names": text_to_list(snapshot["remove_tags"]),
            "remove_heading_keywords": text_to_list(snapshot["ignore_sections"]),
        },
        "dom_clean_config": {
            **base_config.dom_clean_config,
            "allowed_tags": text_to_list(snapshot["keep_tags"]),
            "allowed_attributes": text_to_list(snapshot["allowed_attributes"]),
        },
        "keep_elements": {
            **base_config.keep_elements,
            "keep_heading_keywords": text_to_list(snapshot["keywords"]),
        },
    })
    return payload


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def _do_select(target_id: Optional[str]) -> None:
    """Loads target_id (or a blank default for "__new__", or clears the
    panel for None) into session_state. Only called from an explicit
    state-transition action - never from the main render path - so it can
    never clobber an in-progress edit mid-rerun."""
    st.session_state["cm_selected_id"] = target_id
    st.session_state["cm_confirm_delete"] = False
    st.session_state["cm_save_as_open"] = False

    if target_id is None:
        st.session_state["cm_loaded_config"] = None
        st.session_state["cm_original_snapshot"] = None
        return

    if target_id == "__new__":
        config = WebsiteConfig()
    else:
        ok, config = safe_call(config_service.get, target_id)
        if not ok:
            st.session_state["cm_selected_id"] = None
            return

    snapshot = _snapshot_from_config(config, is_new=(target_id == "__new__"))
    st.session_state["cm_loaded_config"] = config
    st.session_state["cm_original_snapshot"] = snapshot
    _apply_snapshot_to_session_state(snapshot)


def _request_select(target_id: Optional[str]) -> None:
    current_id = st.session_state.get("cm_selected_id")
    if target_id == current_id:
        return
    if current_id is not None and is_dirty(_read_current_snapshot(), st.session_state.get("cm_original_snapshot") or {}):
        st.session_state["cm_pending_selection"] = target_id
        st.session_state["cm_show_unsaved_dialog"] = True
    else:
        _do_select(target_id)
    st.rerun()


def _request_reselect(target_id: Optional[str]) -> None:
    """Schedules _do_select(target_id) to run at the top of the *next*
    script run, before any cmf_* widget is instantiated - see the
    deferred-action comment above the session_state defaults. Callers still
    need to st.rerun() themselves afterward."""
    st.session_state["cm_pending_select_flag"] = True
    st.session_state["cm_pending_select_target"] = target_id


def _save_current() -> bool:
    snapshot = _read_current_snapshot()
    if not snapshot["name"].strip():
        st.error("**Configuration Error**\n\nName is required.")
        return False

    base_config = st.session_state["cm_loaded_config"]
    payload = _build_payload(base_config, snapshot)
    selected_id = st.session_state["cm_selected_id"]

    if selected_id == "__new__":
        ok, new_id = safe_call(config_service.create, payload)
        if not ok:
            return False
        st.success(f"✅ Configuration '{snapshot['name']}' created.")
        _request_reselect(new_id)
    else:
        ok, _ = safe_call(config_service.update, selected_id, payload)
        if not ok:
            return False
        st.success(f"✅ Configuration '{snapshot['name']}' saved.")
        _request_reselect(selected_id)
    return True


def _save_as(new_name: str) -> bool:
    if not new_name.strip():
        st.error("**Configuration Error**\n\nA name is required for Save As.")
        return False

    snapshot = dict(_read_current_snapshot())
    snapshot["name"] = new_name
    base_config = st.session_state["cm_loaded_config"]
    clean_meta = {k: v for k, v in (base_config.metadata or {}).items() if k not in ("created_at", "updated_at")}
    base_for_clone = replace(base_config, metadata=clean_meta)

    payload = _build_payload(base_for_clone, snapshot)
    ok, new_id = safe_call(config_service.create, payload)
    if not ok:
        return False
    st.success(f"✅ Saved as new configuration '{new_name}'.")
    _request_reselect(new_id)
    return True


def _delete_current() -> None:
    selected_id = st.session_state["cm_selected_id"]
    ok, _ = safe_call(config_service.delete, selected_id)
    if ok:
        st.success("✅ Configuration deleted.")
        _request_reselect(None)


def _cancel_changes() -> None:
    """Schedules a reset-to-original for the current selection. Called from
    the Cancel Changes button, which - like Save/Save As/Delete - is
    rendered after the cmf_* widgets this run, so it defers via
    cm_pending_reset_current rather than calling
    _apply_snapshot_to_session_state() directly."""
    st.session_state["cm_pending_reset_current"] = True


# ---------------------------------------------------------------------------
# Deferred-action consumer: must run before any cmf_* widget is
# instantiated this run - see the comment above the session_state defaults.
# Handles home.py's cross-page "New Configuration" request too (nothing
# already selected -> treat like a pending select to "__new__").
# ---------------------------------------------------------------------------
if st.session_state.pop("cm_pending_select_flag", False):
    _do_select(st.session_state.pop("cm_pending_select_target", None))
elif st.session_state.pop("cm_pending_reset_current", False):
    original = st.session_state.get("cm_original_snapshot") or {}
    _apply_snapshot_to_session_state(original)
elif st.session_state.pop("cm_request_new", False) and st.session_state.get("cm_selected_id") is None:
    _do_select("__new__")


# ---------------------------------------------------------------------------
# Unsaved-changes dialog (must be checked before rendering the rest of the
# page, since switching selection routes through it)
# ---------------------------------------------------------------------------

if st.session_state.get("cm_show_unsaved_dialog"):
    def _on_save():
        saved = _save_current()
        if saved:
            _do_select(st.session_state.get("cm_pending_selection"))
            st.session_state["cm_show_unsaved_dialog"] = False
            st.session_state["cm_pending_selection"] = None
        st.rerun()

    def _on_discard():
        _do_select(st.session_state.get("cm_pending_selection"))
        st.session_state["cm_show_unsaved_dialog"] = False
        st.session_state["cm_pending_selection"] = None
        st.rerun()

    def _on_cancel():
        st.session_state["cm_show_unsaved_dialog"] = False
        st.session_state["cm_pending_selection"] = None
        st.rerun()

    show_unsaved_changes_dialog(_on_save, _on_discard, _on_cancel)


# ---------------------------------------------------------------------------
# Left panel: search + list
# ---------------------------------------------------------------------------

def render_left_panel() -> None:
    if st.button("➕ New Configuration", use_container_width=True, type="primary"):
        _request_select("__new__")

    search = st.text_input("🔍 Search", key="cm_search", placeholder="Name, domain, or description...")

    summaries = config_service.list()
    if not summaries:
        st.info("No website configurations yet.")
        return

    rows = []
    for row in summaries:
        ok, full = safe_call(config_service.get, row["id"])
        meta = (full.metadata if ok and full else {}) or {}
        rows.append({
            "id": row["id"],
            "name": row["name"],
            "domain": row["domain"],
            "description": meta.get("description", ""),
            "updated_at": meta.get("updated_at", ""),
        })

    if search.strip():
        q = search.strip().lower()
        rows = [
            r for r in rows
            if q in r["name"].lower() or q in r["domain"].lower() or q in r["description"].lower()
        ]

    if not rows:
        st.caption("No configurations match your search.")
        return

    selected_id = st.session_state.get("cm_selected_id")
    for r in rows:
        clicked = render_list_row(
            title=r["name"],
            subtitle=r["domain"],
            caption=f"Last modified: {r['updated_at']}" if r["updated_at"] else "",
            is_selected=(r["id"] == selected_id),
            button_key=f"cm_row_{r['id']}",
        )
        if clicked:
            _request_select(r["id"])


# ---------------------------------------------------------------------------
# Right panel: summary + editor
# ---------------------------------------------------------------------------

def _render_summary(snapshot: Dict[str, Any]) -> None:
    st.markdown("##### Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Name", snapshot["name"] or "—")
    c2.metric("Domain", snapshot["domain"] or "—")
    c3.metric("Priority", snapshot["priority"])
    browser_opts = sum([bool(snapshot["scroll_enabled"]), bool(snapshot["infinite_scroll"]), bool(snapshot["click_tabs_enabled"])])
    c4.metric("Browser Options Enabled", f"{browser_opts}/3")

    c5, c6 = st.columns(2)
    c5.metric("Relevant DOM Keywords", len(text_to_list(snapshot["keywords"])))
    dom_rules = (
        len(text_to_list(snapshot["remove_tags"]))
        + len(text_to_list(snapshot["keep_tags"]))
        + len(text_to_list(snapshot["ignore_sections"]))
    )
    c6.metric("DOM Cleaning Rules", dom_rules)
    st.divider()


def render_right_panel() -> None:
    selected_id = st.session_state.get("cm_selected_id")
    if selected_id is None:
        st.info("No configuration selected")
        return

    is_new = selected_id == "__new__"
    snapshot = _read_current_snapshot()
    dirty = is_dirty(snapshot, st.session_state.get("cm_original_snapshot") or {})

    st.subheader("➕ New Configuration" if is_new else f"✏️ {snapshot['name'] or 'Edit Configuration'}")
    if dirty:
        st.caption("🟠 Unsaved changes")

    _render_summary(snapshot)

    st.markdown("##### General")
    st.text_input("Name*", key="cmf_name")
    st.text_area("Description", key="cmf_description")
    st.text_input(
        "Domain", key="cmf_domain",
        help="The website domain this config targets (e.g. example.com), or '*' for a generic/reusable config.",
    )
    st.number_input(
        "Priority", key="cmf_priority", step=1,
        help="Higher priority configs are preferred when more than one might match a domain.",
    )

    st.markdown("##### Browser Configuration")
    bc1, bc2 = st.columns(2)
    with bc1:
        st.number_input("Wait Time (ms after page load)", key="cmf_wait_time_ms", min_value=0, step=100)
        st.checkbox("Scroll Enabled", key="cmf_scroll_enabled")
        st.checkbox("Infinite Scroll (expand lazy-loaded content)", key="cmf_infinite_scroll")
    with bc2:
        st.number_input("Timeout (ms)", key="cmf_timeout_ms", min_value=1000, step=1000)
        st.number_input(
            "Max Scrolls", key="cmf_max_scrolls", min_value=0, step=1,
            disabled=not st.session_state.get("cmf_scroll_enabled", True),
        )
    st.checkbox("Click Tabs", key="cmf_click_tabs_enabled")
    st.text_input(
        "Tab keywords to click (comma-separated)", key="cmf_click_tab_keywords",
        disabled=not st.session_state.get("cmf_click_tabs_enabled", False),
        help="Only tabs whose visible text contains one of these words are clicked (e.g. profile, details, faq).",
    )

    st.markdown("##### DOM Cleaning")
    dc1, dc2 = st.columns(2)
    with dc1:
        st.text_input(
            "Remove Tags (comma-separated)", key="cmf_remove_tags",
            help="HTML tags removed outright before anything else runs (e.g. nav, footer, aside).",
        )
    with dc2:
        st.text_input(
            "Keep Tags (comma-separated)", key="cmf_keep_tags",
            help="If set, only these tags survive cleaning (their content is kept, other tags are unwrapped).",
        )
    st.text_input(
        "Allowed Attributes (comma-separated)", key="cmf_allowed_attributes",
        help="Reserved for a future DOM-cleaning enhancement - not yet enforced by the pipeline.",
    )

    st.markdown("##### Relevant DOM")
    rd1, rd2 = st.columns(2)
    with rd1:
        st.text_area(
            "Keywords to keep (comma-separated)", key="cmf_keywords",
            help="Sections whose headings mention these words are always kept.",
        )
    with rd2:
        st.text_area(
            "Ignore Sections (comma-separated)", key="cmf_ignore_sections",
            help="Sections whose headings mention these words are actively pruned (e.g. related listings, ads).",
        )

    st.markdown("##### Advanced")
    with st.expander("Raw config (read-only)"):
        st.json(st.session_state["cm_loaded_config"].to_dict())

    st.divider()
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("💾 Save", use_container_width=True, type="primary"):
        if _save_current():
            st.rerun()
    if b2.button("📄 Save As", use_container_width=True, disabled=is_new):
        st.session_state["cm_save_as_open"] = True
    if b3.button("🗑️ Delete", use_container_width=True, disabled=is_new):
        st.session_state["cm_confirm_delete"] = True
    if b4.button("↩️ Cancel Changes", use_container_width=True, disabled=not dirty):
        _cancel_changes()
        st.rerun()

    if st.session_state.get("cm_save_as_open"):
        st.markdown("###### Save As")
        sa1, sa2, sa3 = st.columns([3, 1, 1])
        new_name = sa1.text_input("New configuration name", value=f"{snapshot['name']} (Copy)", key="cm_save_as_name", label_visibility="collapsed")
        if sa2.button("Confirm", key="cm_save_as_confirm", use_container_width=True):
            if _save_as(new_name):
                st.session_state["cm_save_as_open"] = False
                st.rerun()
        if sa3.button("Cancel", key="cm_save_as_cancel", use_container_width=True):
            st.session_state["cm_save_as_open"] = False
            st.rerun()

    if st.session_state.get("cm_confirm_delete"):
        st.warning(f"Delete configuration **{snapshot['name']}**? This cannot be undone.")
        d1, d2 = st.columns(2)
        if d1.button("Yes, delete it", type="primary", key="cm_delete_confirm"):
            _delete_current()
            st.rerun()
        if d2.button("Cancel", key="cm_delete_cancel"):
            st.session_state["cm_confirm_delete"] = False
            st.rerun()


# ---------------------------------------------------------------------------
left, right = st.columns([1, 2])
with left:
    render_left_panel()
with right:
    render_right_panel()
