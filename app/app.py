import streamlit as st
import asyncio
import time
import os
import sys
import json
import pandas as pd
from typing import Any, Dict, List, Optional

# Add the parent directory to python path for modular package resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.adapter_loader import AdapterLoader, ExtractionResult
from utils.logger import get_logger

logger = get_logger(__name__)

# Configure Streamlit page defaults
st.set_page_config(
    page_title="Data Extractor",
    page_icon="🔍",
    layout="wide"
)

# Render the simple title as requested
st.title("Data Extractor")

# URL Input and optional guidelines
target_url = st.text_input("URL", placeholder="Enter single URL to extract data from...")
uploaded_file = st.file_uploader("Or upload a .txt file containing URLs (one per line)", type=["txt"])
instructions = st.text_area("Extraction Guidelines (Optional)", placeholder="e.g. Only extract specific fields, filter by criteria, etc.")

if st.button("Extract", type="primary", width="stretch"):
    urls = []
    
    # 1. Collect from text input
    if target_url.strip():
        urls.append(target_url.strip())
        
    # 2. Collect from uploaded file
    if uploaded_file is not None:
        try:
            content = uploaded_file.read().decode("utf-8")
            for line in content.splitlines():
                line_clean = line.strip()
                if line_clean.startswith("http://") or line_clean.startswith("https://"):
                    urls.append(line_clean)
        except Exception as fe:
            st.error(f"Error reading uploaded file: {fe}")
            
    # Remove duplicates but keep order
    seen = set()
    urls = [x for x in urls if not (x in seen or seen.add(x))]
    
    if not urls:
        st.error("Please provide at least one valid URL via input textbox or file upload.")
    else:
        # Create placeholders for each URL rendering before execution starts
        st.write("### Live Extraction Progress")
        url_containers = []
        for idx, u in enumerate(urls):
            st.markdown(f"**URL #{idx+1}:** `{u}`")
            status = st.empty()
            stages = st.empty()
            logs = st.empty()
            st.markdown("---")
            url_containers.append((status, stages, logs))

        # Async execution queue with Semaphores
        async def run_batch_extraction():
            sem = asyncio.Semaphore(2)  # Limit concurrency to prevent rate-limiting (429)
            completed_count = 0
            total_urls = len(urls)
            
            progress_bar = st.progress(0)
            
            async def process_single_url(url, idx):
                nonlocal completed_count
                status_placeholder, stages_placeholder, logs_placeholder = url_containers[idx]
                
                async with sem:
                    def progress_callback(data):
                        # Construct a markdown list of stages with execution status
                        stages_md = ""
                        for stage_name, info in data["stages"].items():
                            status = info["status"]
                            dur = info["duration"]
                            if status == "Completed":
                                icon = "✅"
                            elif status == "Running":
                                icon = "⏳"
                            elif status.startswith("Failed"):
                                icon = "❌"
                            else:
                                icon = "⚪"
                            
                            dur_str = f" ({dur:.2f}s)" if dur > 0 else ""
                            stages_md += f"* {icon} **{stage_name}**: `{status}`{dur_str}\n"
                        
                        total_time = data["total_time"]
                        stages_md += f"\n**Total elapsed time:** {total_time:.2f}s"
                        stages_placeholder.markdown(stages_md)
                        
                        logs_to_show = data["logs"][-5:]
                        logs_md = "```\n" + "\n".join(logs_to_show) + "\n```"
                        logs_placeholder.markdown(logs_md)

                    try:
                        from core.pipeline import FranchiseExtractionPipeline
                        pipeline = FranchiseExtractionPipeline(progress_callback=progress_callback)
                        
                        status_placeholder.markdown(f"⏳ **Extraction Pipeline Running...**")
                        pipeline_res = await pipeline.run(url, user_instructions=instructions)
                        
                        completed_count += 1
                        progress_bar.progress(completed_count / total_urls)
                        
                        status_placeholder.markdown(f"✅ **Completed in {pipeline_res['duration']:.2f}s!**")
                        
                        # Generate quality report
                        quality_report = {}
                        try:
                            from modules.evaluation.quality_evaluator import ExtractionQualityEvaluator
                            from modules.preprocessor import estimate_tokens
                            
                            result = pipeline_res["result"]
                            adapter = AdapterLoader.load(url)
                            schema = adapter.schema
                            req_fields = schema.get("required_fields", [])
                            
                            filtered_html = ""
                            for meta_item in result.metadata:
                                if meta_item.key == "filtered_html":
                                    filtered_html = str(meta_item.value)
                                    break
                            
                            tok_count = estimate_tokens(filtered_html) if filtered_html else 0
                            
                            evaluator = ExtractionQualityEvaluator()
                            quality_report = evaluator.evaluate(
                                result=result,
                                html_content=filtered_html or "",
                                execution_time=pipeline_res["duration"],
                                token_count=tok_count,
                                schema_required=req_fields,
                                source_url=url
                            )
                        except Exception as eval_err:
                            logger.error(f"Quality report error: {eval_err}")
                            
                        return url, {
                            "status": "success", 
                            "result": pipeline_res["result"], 
                            "mapped_record": pipeline_res["mapped_record"],
                            "execution_time": pipeline_res["duration"],
                            "dataset_status": pipeline_res["save_info"],
                            "quality_report": quality_report,
                            "pipeline_logs": pipeline.logs,
                            "stages_durations": pipeline.stages
                        }
                    except Exception as e:
                        completed_count += 1
                        progress_bar.progress(completed_count / total_urls)
                        status_placeholder.markdown(f"❌ **Failed:** {e}")
                        return url, {"status": "error", "error": str(e)}

            tasks = [process_single_url(url, idx) for idx, url in enumerate(urls)]
            results_list = await asyncio.gather(*tasks)
            progress_bar.empty()
            return dict(results_list)

        try:
            start_time = time.time()
            results = asyncio.run(run_batch_extraction())
            elapsed_time = time.time() - start_time
            
            from modules.gemini import QuotaManager
            if QuotaManager.is_exhausted():
                st.error("🛑 **Gemini daily quota exhausted.** Please try again tomorrow or configure another API key.")
            else:
                st.success(f"Successfully processed {len(results)} URLs in {elapsed_time:.2f} seconds!")
            
            st.session_state["batch_results"] = results
            
        except Exception as e:
            st.error(f"An error occurred during execution: {e}")
            logger.error(f"Streamlit extraction failed: {e}", exc_info=True)

# Display results if available in session state
if "batch_results" in st.session_state:
    batch_results = st.session_state["batch_results"]
    
    st.markdown("---")
    st.subheader("Results Viewer")
    
    urls_keys = list(batch_results.keys())
    selected_url = st.selectbox("Select URL to view extracted data", urls_keys)
    
    if selected_url:
        res_info = batch_results[selected_url]
        if res_info["status"] == "error":
            st.error(f"Extraction failed for this URL: {res_info['error']}")
        else:
            result: ExtractionResult = res_info["result"]
            execution_time = res_info.get("execution_time", 0.0)
            clean_data = result.to_clean_dict()
            
            # Show detected adapter name
            adapter = AdapterLoader.load(selected_url)
            st.info(f"🔌 **Matched Adapter:** `{adapter.name}` (Domain: `{adapter.domain}`, Version: `{getattr(adapter, 'version', '1.0.0')}`)")

            # Build unified metadata dictionary
            metadata_dict = {}
            if hasattr(result, "metadata") and result.metadata:
                for item in result.metadata:
                    if hasattr(item, "key") and hasattr(item, "value"):
                        metadata_dict[item.key] = item.value
                    elif isinstance(item, dict) and "key" in item and "value" in item:
                        metadata_dict[item["key"]] = item["value"]

            mapped_record = res_info.get("mapped_record")
            
            if mapped_record:
                # Direct MappingResult retrieval
                cov_stats = getattr(mapped_record, "coverage_statistics", {})
                norm_stats = getattr(mapped_record, "normalization_statistics", {})
                
                cov_pct = cov_stats.get("coverage_percentage", "0.0%")
                mapped_c = cov_stats.get("mapped_count", "0")
                total_c = cov_stats.get("total_schema_fields", "0")
                norm_c = norm_stats.get("normalized_count", "0")
                merged_c = norm_stats.get("merged_count", "0")
                
                unmapped_list = cov_stats.get("unmapped_fields_list", "")
                missing_list = cov_stats.get("missing_fields_list", "")
            else:
                cov_pct = metadata_dict.get("coverage_percentage", "0.0%")
                mapped_c = metadata_dict.get("mapped_count", "0")
                total_c = metadata_dict.get("total_schema_fields", "0")
                norm_c = metadata_dict.get("normalized_count", "0")
                merged_c = metadata_dict.get("merged_count", "0")
                
                unmapped_list = metadata_dict.get("unmapped_fields_list", "")
                missing_list = metadata_dict.get("missing_fields_list", "")

            # Normalize lists
            if isinstance(unmapped_list, str):
                unmapped_fields = [u.strip() for u in unmapped_list.split(",") if u.strip()]
            else:
                unmapped_fields = unmapped_list or []
                
            if isinstance(missing_list, str):
                missing_fields = [m.strip() for m in missing_list.split(",") if m.strip()]
            else:
                missing_fields = missing_list or []

            mapped_c_val = int(mapped_c) if str(mapped_c).isdigit() else 0
            total_c_val = int(total_c) if str(total_c).isdigit() else 0
            quality_score = int((mapped_c_val / total_c_val) * 100) if total_c_val > 0 else 0

            # Count of deterministic fields vs LLM fields
            det_count_val = 0
            llm_count_val = 0
            if mapped_record and hasattr(mapped_record, "confidence_scores"):
                for field_name, score in mapped_record.confidence_scores.items():
                    if score == 1.0 or "exact" in str(mapped_record.mapping_paths.get(field_name, "")).lower():
                        det_count_val += 1
                    else:
                        llm_count_val += 1
            else:
                det_count_val = int(metadata_dict.get("deterministic_count", "0"))
                llm_count_val = int(metadata_dict.get("llm_count", "0"))

            # Calculate DOM Retained %
            dom_retained_pct = "N/A"
            original_tokens = metadata_dict.get("original_tokens")
            filtered_tokens = metadata_dict.get("filtered_tokens")
            if original_tokens and filtered_tokens:
                try:
                    orig_t_val = float(original_tokens)
                    filt_t_val = float(filtered_tokens)
                    if orig_t_val > 0:
                        dom_retained_pct = f"{(filt_t_val / orig_t_val) * 100:.1f}%"
                except Exception:
                    pass
            elif "reduction_pct" in metadata_dict:
                try:
                    red_val = float(metadata_dict["reduction_pct"].replace("%", ""))
                    dom_retained_pct = f"{100.0 - red_val:.1f}%"
                except Exception:
                    pass

            # Calculated extraction coverage metrics
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.metric(label="Extraction Quality Score", value=f"{quality_score}%")
            with col_m2:
                st.metric(label="Execution Duration", value=f"{execution_time:.2f}s")
            with col_m3:
                st.metric(label="Normalized / Merged", value=f"{norm_c} / {merged_c}")
            
            # Render the Adapter Health Report dashboard table
            st.write("### 🔌 Adapter Health Report")
            quality_report = res_info.get("quality_report", {})
            health_df = pd.DataFrame([{
                "Adapter Name": adapter.name,
                "Quality Score": f"{quality_score}%",
                "DOM Retained %": dom_retained_pct,
                "Deterministic Count": det_count_val,
                "Gemini Count": llm_count_val,
                "Normalized Count": norm_c,
                "Merged Count": merged_c,
                "Missing Count": len(missing_fields),
                "Warnings Count": len(quality_report.get("validation_warnings", [])) if quality_report else 0
            }])
            st.dataframe(health_df, use_container_width=True)

            # Display detailed Expandable Diagnostics
            st.write("### 🔍 Pipeline Diagnostics")
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                with st.expander("📊 DOM Statistics"):
                    orig_t = metadata_dict.get("original_tokens", "0")
                    filt_t = metadata_dict.get("filtered_tokens", "0")
                    red_p = metadata_dict.get("reduction_pct", "0.0%")
                    st.write(f"**Original HTML Tokens:** {orig_t}")
                    st.write(f"**Cleaned/Relevant HTML Tokens:** {filt_t}")
                    st.write(f"**Token Reduction Percentage:** {red_p}")
                    st.write(f"**DOM Retained Percentage:** {dom_retained_pct}")
                    
                with st.expander("📥 Deterministic Fields"):
                    if mapped_record:
                        dom_fields_list = [col for col, mapped_info in mapped_record.confidence_scores.items() if mapped_info == 1.0 or "exact" in str(mapped_record.mapping_paths.get(col, "")).lower()]
                        st.write(f"**Count:** {len(dom_fields_list)}")
                        st.write(f"**Fields:** {', '.join(dom_fields_list) if dom_fields_list else 'None'}")
                    else:
                        st.write("No mapping info available.")
                        
                with st.expander("🤖 Gemini Fields"):
                    if mapped_record:
                        gem_fields_list = [col for col, mapped_info in mapped_record.confidence_scores.items() if mapped_info < 1.0 and "exact" not in str(mapped_record.mapping_paths.get(col, "")).lower()]
                        st.write(f"**Count:** {len(gem_fields_list)}")
                        st.write(f"**Fields:** {', '.join(gem_fields_list) if gem_fields_list else 'None'}")
                    else:
                        st.write("No mapping info available.")
            with col_d2:
                with st.expander("🔄 Validator Changes (Original vs Normalized)"):
                    st.write("**Applied normalizations (Original -> Normalized):**")
                    found_norm = False
                    for k_meta, v_meta in metadata_dict.items():
                        if k_meta.startswith("normalized_from_"):
                            field_name = k_meta.replace("normalized_from_", "")
                            curr_val = getattr(result, field_name, None)
                            st.write(f"* `{field_name}`: *'{v_meta}'* -> **'{curr_val}'**")
                            found_norm = True
                    if not found_norm:
                        st.info("No normalization changes applied to this record.")
                        
                with st.expander("🗺 Schema Mapping Paths"):
                    if mapped_record and hasattr(mapped_record, "mapping_paths"):
                        st.write("**Diagnostic Mapping Paths:**")
                        for col, path in mapped_record.mapping_paths.items():
                            st.write(f"* **{col}**: `{path}`")
                    else:
                        paths_json = metadata_dict.get("mapping_paths_json")
                        if paths_json:
                            try:
                                paths_data = json.loads(paths_json)
                                for col, path in paths_data.items():
                                    st.write(f"* **{col}**: `{path}`")
                            except Exception:
                                st.write("Failed to parse mapping paths.")
                        else:
                            st.write("No mapping path info available.")

            # Display unmapped and missing fields warnings
            if unmapped_fields or missing_fields:
                with st.expander("🔍 Show Unmapped / Missing Schema Fields"):
                    if unmapped_fields:
                        st.warning(f"⚠️ **Unmapped Fields (not in spreadsheet columns)**: " + ", ".join(f"`{u.strip()}`" for u in unmapped_fields))
                    if missing_fields:
                        st.info(f"ℹ️ **Missing Fields (not found in extraction)**: " + ", ".join(f"`{m.strip()}`" for m in missing_fields))

            # Pretty view of Additional Information if present
            if mapped_record and hasattr(mapped_record, "mapped_record") and "Additional Information" in mapped_record.mapped_record:
                add_info_val = mapped_record.mapped_record["Additional Information"]
                if add_info_val:
                    try:
                        import json
                        parsed_info = json.loads(add_info_val)
                        if parsed_info:
                            with st.expander("ℹ️ Show Pretty View: Additional Information Fallback Data"):
                                st.json(parsed_info)
                    except Exception:
                        pass

            # Dataset Save Confirmation
            dataset_status = res_info.get("dataset_status", {})
            if dataset_status:
                if dataset_status.get("status") == "Success":
                    op = dataset_status.get("operation", "Inserted")
                    wb_name = dataset_status.get("workbook_name", "")
                    row_num = dataset_status.get("row_number", "")
                    st.success(f"✅ Workbook: `{wb_name}` | Operation: `{op}` | Target Row: `{row_num}`")
                else:
                    st.warning(f"⚠ Excel Update Skipped: {dataset_status.get('error', 'File locked/failed')}")
            
            st.markdown("---")
            
            # 1. Main Page Metadata
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown(f"**Detected Page Type:** {result.page_type}")
                st.markdown(f"**Page Title:** {result.page_title}")
            with col2:
                st.markdown(f"**Summary:** {result.page_summary}")
                
            st.markdown("---")
            
            # 1.25. Stage Durations
            st.subheader("⏱ Stage Execution Times")
            durations_data = []
            for stage_name, info in res_info.get("stages_durations", {}).items():
                durations_data.append({
                    "Stage": stage_name,
                    "Status": info["status"],
                    "Duration (seconds)": f"{info['duration']:.3f}s" if info["duration"] > 0 else "-"
                })
            st.dataframe(pd.DataFrame(durations_data), use_container_width=True)
            
            st.markdown("---")
            
            # 1.5. Extraction Quality report
            from modules.config import ExtractorConfig
            app_config = ExtractorConfig.load()
            quality_report = res_info.get("quality_report", {})
            if quality_report and app_config.DEVELOPER_MODE:
                st.subheader("📊 Extraction Quality Report")
                
                qcol1, qcol2, qcol3 = st.columns(3)
                with qcol1:
                    st.metric(label="Coverage Score", value=quality_report.get("coverage_ratio", "N/A"), 
                              help=f"{quality_report.get('coverage_percentage', 0.0):.1f}% of schema fields extracted.")
                with qcol2:
                    conf = quality_report.get("confidence_score", 0.0)
                    st.metric(label="Confidence Rating", value=f"{conf:.1f}%")
                with qcol3:
                    if conf >= 80.0:
                        st.success("🟢 High Confidence")
                    elif conf >= 50.0:
                        st.warning("🟡 Medium Confidence")
                    else:
                        st.error("🔴 Low Confidence")

                warnings = quality_report.get("validation_warnings", [])
                hallucinations = quality_report.get("hallucinations", [])
                missed = quality_report.get("likely_missed_fields", [])
                
                if warnings or hallucinations or missed:
                    st.markdown("##### 🔍 Quality Observations")
                    if missed:
                        st.markdown(f"⚠️ **Likely Missed Fields**: " + ", ".join(f"`{m}`" for m in missed))
                    if hallucinations:
                        st.markdown(f"🚨 **Possible Hallucinations**:")
                        for h in hallucinations:
                            st.markdown(f"  * `{h['field']}`: *'{h['value']}'*")
                    if warnings:
                        st.markdown(f"📌 **Validation Warnings**:")
                        for w in warnings:
                            st.markdown(f"  * {w}")
                else:
                    st.success("✅ No schema validation, DOM mismatch, or hallucination warnings detected!")
                
                st.markdown("---")

            # 2. Extracted Entities
            st.subheader("📋 Extracted Data Records")
            for ent_type, records in clean_data["entities"].items():
                st.write(f"#### Entity: **{ent_type}**")
                if records:
                    df_records = pd.DataFrame(records)
                    for col in df_records.columns:
                        if df_records[col].dtype == object:
                            df_records[col] = df_records[col].apply(lambda x: str(x) if (x is not None and not pd.isna(x)) else "")
                    st.dataframe(df_records, width="stretch")
                else:
                    st.info("No records found for this entity.")
                    
            st.markdown("---")
            
            # 3. Pipeline Run Logs
            with st.expander("Show Pipeline Execution Logs"):
                st.code("\n".join(res_info.get("pipeline_logs", [])))

            with st.expander("Show Raw Extraction JSON"):
                st.json(clean_data)

    # Consolidated download batch results button
    st.markdown("---")
    consolidated_results = {}
    for url, res_info in batch_results.items():
        if res_info["status"] == "success":
            consolidated_results[url] = {
                "raw_result": res_info["result"].to_clean_dict()
            }
        else:
            consolidated_results[url] = {"error": res_info["error"]}
            
    st.download_button(
        label="Download Consolidated Batch JSON",
        data=json.dumps(consolidated_results, indent=2),
        file_name="batch_extracted_data.json",
        mime="application/json",
        key="btn_download_consolidated",
        width="stretch"
    )
