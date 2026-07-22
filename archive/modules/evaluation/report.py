from typing import Dict, Any

class EvaluationReport:
    """
    Formats the quality evaluation results into logs and UI summaries.
    """

    @staticmethod
    def generate_summary_text(report_data: Dict[str, Any]) -> str:
        """
        Creates a clean CLI/log output report representation.
        """
        lines = [
            "=========================================",
            "        EXTRACTION QUALITY REPORT        ",
            "=========================================",
            f"Coverage             : {report_data['coverage_ratio']} ({report_data['coverage_percentage']:.1f}%)",
            f"Confidence Score     : {report_data['confidence_score']:.1f}%",
            f"Completeness Score   : {report_data['completeness_score']:.1f}%",
            f"DOM Match Score      : {report_data['dom_match_score']:.1f}%",
            "-----------------------------------------",
            f"Likely Missed Fields : {', '.join(report_data['likely_missed_fields']) or 'None'}",
            f"Missing on Page      : {', '.join(report_data['missing_on_page_fields']) or 'None'}",
            f"Possible Hallucinations: {len(report_data['hallucinations'])} found",
        ]
        
        for h in report_data['hallucinations']:
            lines.append(f"  - Field '{h['field']}': Extracted '{h['value']}' (not found in DOM)")
            
        lines.append("-----------------------------------------")
        lines.append(f"Validation Warnings  : {len(report_data['validation_warnings'])} found")
        for w in report_data['validation_warnings']:
            lines.append(f"  - {w}")
            
        lines.append("=========================================")
        return "\n".join(lines)
