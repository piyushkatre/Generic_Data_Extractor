from core.pipeline_context import PipelineContext


def test_pipeline_context_initializes_all_stages_pending():
    ctx = PipelineContext(url="https://example.com", runtime_adapter=None)
    assert set(ctx.stages.keys()) == set(PipelineContext.STAGE_NAMES)
    assert all(s["status"] == "Pending" for s in ctx.stages.values())


def test_pipeline_context_update_stage_and_callback():
    events = []
    ctx = PipelineContext(
        url="https://example.com",
        runtime_adapter=None,
        progress_callback=lambda data: events.append(data),
    )
    ctx.start()
    ctx.update_stage("Browser Rendering", "Running")
    ctx.update_stage("Browser Rendering", "Completed", 1.23)

    assert ctx.stages["Browser Rendering"]["status"] == "Completed"
    assert ctx.stages["Browser Rendering"]["duration"] == 1.23
    assert len(events) == 2
    assert events[-1]["stages"]["Browser Rendering"]["status"] == "Completed"


def test_pipeline_context_log_accumulates_messages():
    ctx = PipelineContext(url="https://example.com", runtime_adapter=None)
    ctx.log("first message")
    ctx.log("second message")
    assert len(ctx.logs) == 2
    assert "first message" in ctx.logs[0]


def test_pipeline_context_page_type_is_informational_only():
    ctx = PipelineContext(url="https://example.com", runtime_adapter=None)
    assert ctx.detected_page_type is None
    ctx.set_page_type("Product Page", 0.82)
    assert ctx.detected_page_type == "Product Page"
    assert ctx.detected_page_type_confidence == 0.82


def test_pipeline_context_reuses_externally_provided_stages_dict():
    external_stages = {"Custom Stage": {"status": "Pending", "duration": 0.0}}
    ctx = PipelineContext(url="https://example.com", runtime_adapter=None, stages=external_stages)
    assert ctx.stages is external_stages
