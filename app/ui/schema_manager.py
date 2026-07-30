"""
Extraction Schema Manager - search/list/create/edit/save-as/delete
ExtractionSchema, via SchemaService only (never SchemaStore directly).

Same two-panel architecture as config_manager.py (see its module docstring
and app/ui/_manager_ui.py for the shared dirty-check/dialog/list-row
helpers): a left search+list panel, and a right summary+editor panel that
always shows the selected schema (or "No schema selected").

The field list (st.session_state["smf_fields"]) is a plain, live-mutated
list of dicts mirroring ExtractionField's constructor kwargs - each field's
widgets write their return value directly into that list's dict entries
in place (not via widget key/session_state sync), so add/remove/reorder
and the dirty-check both see the same object every rerun.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import streamlit as st

from app.ui._services import get_schema_service
from app.ui._errors import safe_call
from app.ui._manager_ui import is_dirty, render_list_row, show_unsaved_changes_dialog, text_to_list, list_to_text
from config.extraction_schema import ExtractionSchema, ExtractionField
from core.field_matching import normalize_field_name

st.set_page_config(page_title="Schema Manager", page_icon="🧩", layout="wide")
st.title("🧩 Extraction Schema Manager")

schema_service = get_schema_service()

FIELD_TYPES = ["string", "array", "integer", "number", "boolean"]

st.session_state.setdefault("sm_selected_id", None)
st.session_state.setdefault("sm_loaded_schema", None)
st.session_state.setdefault("sm_original_snapshot", None)
st.session_state.setdefault("sm_pending_selection", None)
st.session_state.setdefault("sm_show_unsaved_dialog", False)
st.session_state.setdefault("sm_confirm_delete", False)
st.session_state.setdefault("sm_save_as_open", False)
st.session_state.setdefault("smf_name", "")
st.session_state.setdefault("smf_dataset_name", "")
st.session_state.setdefault("smf_sheet_name", "General Web Data")
st.session_state.setdefault("smf_fields", [])
# Metadata columns (Source URL / Page Title) - pipeline-owned values, never
# extraction fields; see core.field_matching.SUPPORTED_METADATA_COLUMNS.
st.session_state.setdefault("smf_metadata_source_url", True)
st.session_state.setdefault("smf_metadata_page_title", True)
# Deferred-action markers - see the matching comment in config_manager.py.
# Save/Save As/Delete/Cancel Changes are rendered after the smf_* widgets
# within the same run, so they can't touch those session_state keys
# directly; they set one of these instead and rerun.
st.session_state.setdefault("sm_pending_select_flag", False)
st.session_state.setdefault("sm_pending_select_target", None)
st.session_state.setdefault("sm_pending_reset_current", False)


# ---------------------------------------------------------------------------
# Snapshot <-> session_state <-> ExtractionSchema conversions
# ---------------------------------------------------------------------------

def _field_to_dict(f: ExtractionField) -> Dict[str, Any]:
    return {
        "name": f.name,
        "type": f.type,
        "description": f.description,
        "aliases": list_to_text(f.aliases),
        "required": f.required,
        "extraction_owner": f.extraction_owner or "",
        "merge_policy": f.merge_policy or "",
        "format": f.format or "",
    }


def _snapshot_from_schema(schema: ExtractionSchema, is_new: bool) -> Dict[str, Any]:
    normalized_metadata = {normalize_field_name(m) for m in schema.metadata_columns}
    return {
        "name": "" if is_new else schema.name,
        "dataset_name": schema.dataset_name or "",
        "sheet_name": schema.sheet_name or "General Web Data",
        "fields": [_field_to_dict(f) for f in schema.fields],
        "metadata_source_url": "source_url" in normalized_metadata,
        "metadata_page_title": "page_title" in normalized_metadata,
    }


def _apply_snapshot_to_session_state(snapshot: Dict[str, Any]) -> None:
    st.session_state["smf_name"] = snapshot["name"]
    st.session_state["smf_dataset_name"] = snapshot["dataset_name"]
    st.session_state["smf_sheet_name"] = snapshot["sheet_name"]
    st.session_state["smf_fields"] = copy.deepcopy(snapshot["fields"])
    st.session_state["smf_metadata_source_url"] = snapshot["metadata_source_url"]
    st.session_state["smf_metadata_page_title"] = snapshot["metadata_page_title"]
    # Per-field widgets (fld_name_0, fld_type_1, ...) are keyed by list
    # index, not field identity - once such a key exists, Streamlit uses it
    # over any fresh value= passed to that widget. Without this, switching
    # to a different schema (or reloading after Save/Cancel Changes) would
    # leak stale field values from whatever was previously at that index.
    for key in [k for k in st.session_state.keys() if k.startswith("fld_")]:
        del st.session_state[key]


def _read_current_snapshot() -> Dict[str, Any]:
    return {
        "name": st.session_state.get("smf_name", ""),
        "dataset_name": st.session_state.get("smf_dataset_name", ""),
        "sheet_name": st.session_state.get("smf_sheet_name", ""),
        "fields": copy.deepcopy(st.session_state.get("smf_fields", [])),
        "metadata_source_url": st.session_state.get("smf_metadata_source_url", True),
        "metadata_page_title": st.session_state.get("smf_metadata_page_title", True),
    }


def _build_payload(base_schema: ExtractionSchema, snapshot: Dict[str, Any], name_override: Optional[str] = None) -> Dict[str, Any]:
    payload = base_schema.to_dict()
    metadata_columns = []
    if snapshot["metadata_source_url"]:
        metadata_columns.append("source_url")
    if snapshot["metadata_page_title"]:
        metadata_columns.append("page_title")
    payload.update({
        "name": (name_override or snapshot["name"]).strip(),
        "dataset_name": snapshot["dataset_name"].strip() or None,
        "sheet_name": snapshot["sheet_name"].strip() or "General Web Data",
        "fields": [
            {
                "name": f["name"].strip(),
                "type": f["type"],
                "description": f.get("description", ""),
                "aliases": text_to_list(f.get("aliases", "")),
                "required": bool(f.get("required", False)),
                "extraction_owner": f.get("extraction_owner") or None,
                "merge_policy": f.get("merge_policy") or None,
                "format": f.get("format") or None,
            }
            for f in snapshot["fields"]
        ],
        "metadata_columns": metadata_columns,
    })
    return payload


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def _do_select(target_id: Optional[str]) -> None:
    st.session_state["sm_selected_id"] = target_id
    st.session_state["sm_confirm_delete"] = False
    st.session_state["sm_save_as_open"] = False

    if target_id is None:
        st.session_state["sm_loaded_schema"] = None
        st.session_state["sm_original_snapshot"] = None
        return

    if target_id == "__new__":
        schema = ExtractionSchema()
    else:
        ok, schema = safe_call(schema_service.get, target_id)
        if not ok:
            st.session_state["sm_selected_id"] = None
            return

    snapshot = _snapshot_from_schema(schema, is_new=(target_id == "__new__"))
    st.session_state["sm_loaded_schema"] = schema
    st.session_state["sm_original_snapshot"] = snapshot
    _apply_snapshot_to_session_state(snapshot)


def _request_select(target_id: Optional[str]) -> None:
    current_id = st.session_state.get("sm_selected_id")
    if target_id == current_id:
        return
    if current_id is not None and is_dirty(_read_current_snapshot(), st.session_state.get("sm_original_snapshot") or {}):
        st.session_state["sm_pending_selection"] = target_id
        st.session_state["sm_show_unsaved_dialog"] = True
    else:
        _do_select(target_id)
    st.rerun()


def _validate_snapshot(snapshot: Dict[str, Any]) -> Optional[str]:
    if not snapshot["name"].strip():
        return "Schema name is required."
    if any(not f.get("name", "").strip() for f in snapshot["fields"]):
        return "Every field needs a name."
    return None


def _request_reselect(target_id: Optional[str]) -> None:
    """Schedules _do_select(target_id) for the top of the *next* run,
    before any smf_* widget is instantiated - see the deferred-action
    comment above the session_state defaults."""
    st.session_state["sm_pending_select_flag"] = True
    st.session_state["sm_pending_select_target"] = target_id


def _save_current() -> bool:
    snapshot = _read_current_snapshot()
    error = _validate_snapshot(snapshot)
    if error:
        st.error(f"**Configuration Error**\n\n{error}")
        return False

    base_schema = st.session_state["sm_loaded_schema"]
    payload = _build_payload(base_schema, snapshot)
    selected_id = st.session_state["sm_selected_id"]

    if selected_id == "__new__":
        ok, new_id = safe_call(schema_service.create, payload)
        if not ok:
            return False
        st.success(f"✅ Schema '{snapshot['name']}' created.")
        _request_reselect(new_id)
    else:
        ok, _ = safe_call(schema_service.update, selected_id, payload)
        if not ok:
            return False
        st.success(f"✅ Schema '{snapshot['name']}' saved.")
        _request_reselect(selected_id)
    return True


def _save_as(new_name: str) -> bool:
    if not new_name.strip():
        st.error("**Configuration Error**\n\nA name is required for Save As.")
        return False

    snapshot = _read_current_snapshot()
    error = _validate_snapshot(snapshot)
    if error:
        st.error(f"**Configuration Error**\n\n{error}")
        return False

    snapshot["name"] = new_name
    base_schema = st.session_state["sm_loaded_schema"]
    payload = _build_payload(base_schema, snapshot, name_override=new_name)
    ok, new_id = safe_call(schema_service.create, payload)
    if not ok:
        return False
    st.success(f"✅ Saved as new schema '{new_name}'.")
    _request_reselect(new_id)
    return True


def _delete_current() -> None:
    selected_id = st.session_state["sm_selected_id"]
    ok, _ = safe_call(schema_service.delete, selected_id)
    if ok:
        st.success("✅ Schema deleted.")
        _request_reselect(None)


def _cancel_changes() -> None:
    """Schedules a reset-to-original for the current selection - deferred
    for the same reason as _request_reselect (Cancel Changes is rendered
    after the smf_* widgets this run)."""
    st.session_state["sm_pending_reset_current"] = True


# ---------------------------------------------------------------------------
# Deferred-action consumer: must run before any smf_* widget is
# instantiated this run - see the comment above the session_state defaults.
# Handles home.py's cross-page "New Schema" request too (nothing already
# selected -> treat like a pending select to "__new__").
# ---------------------------------------------------------------------------
if st.session_state.pop("sm_pending_select_flag", False):
    _do_select(st.session_state.pop("sm_pending_select_target", None))
elif st.session_state.pop("sm_pending_reset_current", False):
    original = st.session_state.get("sm_original_snapshot") or {}
    _apply_snapshot_to_session_state(original)
elif st.session_state.pop("sm_request_new", False) and st.session_state.get("sm_selected_id") is None:
    _do_select("__new__")


# ---------------------------------------------------------------------------
# Unsaved-changes dialog
# ---------------------------------------------------------------------------

if st.session_state.get("sm_show_unsaved_dialog"):
    def _on_save():
        saved = _save_current()
        if saved:
            _do_select(st.session_state.get("sm_pending_selection"))
            st.session_state["sm_show_unsaved_dialog"] = False
            st.session_state["sm_pending_selection"] = None
        st.rerun()

    def _on_discard():
        _do_select(st.session_state.get("sm_pending_selection"))
        st.session_state["sm_show_unsaved_dialog"] = False
        st.session_state["sm_pending_selection"] = None
        st.rerun()

    def _on_cancel():
        st.session_state["sm_show_unsaved_dialog"] = False
        st.session_state["sm_pending_selection"] = None
        st.rerun()

    show_unsaved_changes_dialog(_on_save, _on_discard, _on_cancel)


# ---------------------------------------------------------------------------
# Left panel: search + list
# ---------------------------------------------------------------------------

def render_left_panel() -> None:
    if st.button("➕ New Schema", use_container_width=True, type="primary"):
        _request_select("__new__")

    search = st.text_input("🔍 Search", key="sm_search", placeholder="Name, dataset, field, or alias...")

    summaries = schema_service.list()
    if not summaries:
        st.info("No extraction schemas yet.")
        return

    rows = []
    for row in summaries:
        ok, full = safe_call(schema_service.get, row["id"])
        rows.append({
            "id": row["id"],
            "name": row["name"],
            "field_count": row["field_count"],
            "dataset_name": (full.dataset_name or "") if ok and full else "",
            "field_names": [f.name for f in full.fields] if ok and full else [],
            "aliases": [a for f in (full.fields if ok and full else []) for a in (f.aliases or [])],
        })

    if search.strip():
        q = search.strip().lower()
        rows = [
            r for r in rows
            if q in r["name"].lower()
            or q in r["dataset_name"].lower()
            or any(q in fn.lower() for fn in r["field_names"])
            or any(q in a.lower() for a in r["aliases"])
        ]

    if not rows:
        st.caption("No schemas match your search.")
        return

    selected_id = st.session_state.get("sm_selected_id")
    for r in rows:
        clicked = render_list_row(
            title=r["name"],
            subtitle=f"{r['field_count']} field(s)",
            caption=f"Dataset: {r['dataset_name']}" if r["dataset_name"] else "",
            is_selected=(r["id"] == selected_id),
            button_key=f"sm_row_{r['id']}",
        )
        if clicked:
            _request_select(r["id"])


# ---------------------------------------------------------------------------
# Right panel: summary + editor
# ---------------------------------------------------------------------------

def _render_summary(snapshot: Dict[str, Any]) -> None:
    st.markdown("##### Summary")
    fields = snapshot["fields"]
    required_count = sum(1 for f in fields if f.get("required"))
    aliases_count = sum(len(text_to_list(f.get("aliases", ""))) for f in fields)

    c1, c2, c3 = st.columns(3)
    c1.metric("Schema Name", snapshot["name"] or "—")
    c2.metric("Dataset Name", snapshot["dataset_name"] or "—")
    c3.metric("Number of Fields", len(fields))

    c4, c5 = st.columns(2)
    c4.metric("Required Fields", required_count)
    c5.metric("Aliases Count", aliases_count)
    st.divider()


def render_right_panel() -> None:
    selected_id = st.session_state.get("sm_selected_id")
    if selected_id is None:
        st.info("No schema selected")
        return

    is_new = selected_id == "__new__"
    snapshot = _read_current_snapshot()
    dirty = is_dirty(snapshot, st.session_state.get("sm_original_snapshot") or {})

    st.subheader("➕ New Schema" if is_new else f"✏️ {snapshot['name'] or 'Edit Schema'}")
    if dirty:
        st.caption("🟠 Unsaved changes")

    _render_summary(snapshot)

    st.markdown("##### General")
    st.text_input("Schema Name*", key="smf_name")
    ic1, ic2 = st.columns(2)
    with ic1:
        st.text_input("Dataset Name (optional)", key="smf_dataset_name")
    with ic2:
        st.text_input("Sheet Name", key="smf_sheet_name")

    st.markdown("##### Metadata Columns")
    st.caption(
        "Pipeline-provided values, not extraction fields - the LLM and deterministic "
        "extractor never see or produce these; they're copied directly into the output."
    )
    mcol1, mcol2 = st.columns(2)
    with mcol1:
        st.checkbox("Source URL", key="smf_metadata_source_url")
    with mcol2:
        st.checkbox("Page Title", key="smf_metadata_page_title")

    st.markdown("##### Fields")
    fields: List[Dict[str, Any]] = st.session_state["smf_fields"]

    for i, f in enumerate(fields):
        with st.expander(f"Field {i + 1}: {f.get('name') or '(unnamed)'}", expanded=not f.get("name")):
            c1, c2, c3 = st.columns([2, 1, 1])
            f["name"] = c1.text_input("Name", value=f.get("name", ""), key=f"fld_name_{i}")
            f["type"] = c2.selectbox(
                "Type", FIELD_TYPES,
                index=FIELD_TYPES.index(f.get("type", "string")) if f.get("type") in FIELD_TYPES else 0,
                key=f"fld_type_{i}",
            )
            f["required"] = c3.checkbox("Required", value=f.get("required", False), key=f"fld_required_{i}")

            f["description"] = st.text_input("Description", value=f.get("description", ""), key=f"fld_desc_{i}")
            f["aliases"] = st.text_input(
                "Aliases (comma-separated)", value=f.get("aliases", ""), key=f"fld_aliases_{i}",
                help="Alternate names the extractor may recognize this field by.",
            )

            with st.expander("Advanced"):
                f["extraction_owner"] = st.text_input(
                    "Extraction Owner", value=f.get("extraction_owner", ""), key=f"fld_owner_{i}",
                    help="Which extraction stage is authoritative for this field (deterministic vs LLM), if constrained.",
                )
                f["merge_policy"] = st.text_input(
                    "Merge Policy", value=f.get("merge_policy", ""), key=f"fld_merge_{i}",
                    help="How to reconcile this field when multiple extractors produce a value.",
                )
                f["format"] = st.text_input(
                    "Format", value=f.get("format", ""), key=f"fld_format_{i}",
                    help="Expected value format/pattern hint (e.g. currency, date).",
                )

            mc1, mc2, mc4 = st.columns(3)
            if mc1.button("⬆ Move Up", key=f"fld_up_{i}", disabled=i == 0):
                fields[i - 1], fields[i] = fields[i], fields[i - 1]
                st.rerun()
            if mc2.button("⬇ Move Down", key=f"fld_down_{i}", disabled=i == len(fields) - 1):
                fields[i + 1], fields[i] = fields[i], fields[i + 1]
                st.rerun()
            if mc4.button("🗑️ Remove", key=f"fld_remove_{i}"):
                fields.pop(i)
                st.rerun()

    if st.button("➕ Add Field"):
        fields.append({
            "name": "", "type": "string", "description": "", "aliases": "",
            "required": False, "extraction_owner": "", "merge_policy": "", "format": "",
        })
        st.rerun()

    st.markdown("##### Advanced")
    with st.expander("Raw schema (read-only)"):
        st.json(st.session_state["sm_loaded_schema"].to_dict())

    st.divider()
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("💾 Save", use_container_width=True, type="primary"):
        if _save_current():
            st.rerun()
    if b2.button("📄 Save As", use_container_width=True, disabled=is_new):
        st.session_state["sm_save_as_open"] = True
    if b3.button("🗑️ Delete", use_container_width=True, disabled=is_new):
        st.session_state["sm_confirm_delete"] = True
    if b4.button("↩️ Cancel Changes", use_container_width=True, disabled=not dirty):
        _cancel_changes()
        st.rerun()

    if st.session_state.get("sm_save_as_open"):
        st.markdown("###### Save As")
        sa1, sa2, sa3 = st.columns([3, 1, 1])
        new_name = sa1.text_input("New schema name", value=f"{snapshot['name']} (Copy)", key="sm_save_as_name", label_visibility="collapsed")
        if sa2.button("Confirm", key="sm_save_as_confirm", use_container_width=True):
            if _save_as(new_name):
                st.session_state["sm_save_as_open"] = False
                st.rerun()
        if sa3.button("Cancel", key="sm_save_as_cancel", use_container_width=True):
            st.session_state["sm_save_as_open"] = False
            st.rerun()

    if st.session_state.get("sm_confirm_delete"):
        st.warning(f"Delete schema **{snapshot['name']}**? This cannot be undone.")
        d1, d2 = st.columns(2)
        if d1.button("Yes, delete it", type="primary", key="sm_delete_confirm"):
            _delete_current()
            st.rerun()
        if d2.button("Cancel", key="sm_delete_cancel"):
            st.session_state["sm_confirm_delete"] = False
            st.rerun()


# ---------------------------------------------------------------------------
left, right = st.columns([1, 2])
with left:
    render_left_panel()
with right:
    render_right_panel()
