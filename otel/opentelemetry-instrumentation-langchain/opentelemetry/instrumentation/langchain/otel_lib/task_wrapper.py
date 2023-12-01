from opentelemetry import context as context_api

from opentelemetry.instrumentation.utils import _SUPPRESS_INSTRUMENTATION_KEY

from opentelemetry.semconv.ai import SpanAttributes, TraceloopSpanKindValues

from opentelemetry.instrumentation.langchain.utils import _with_tracer_wrapper

def printClassDetails(c):
    attrs = vars(c)    
    print(', '.join("%s: %s" % item for item in attrs.items()))
    
def _set_span_attribute(span, name, value):
    if value is not None:
        if value != "":
            span.set_attribute(name, value)
    return

def _extract_llm_parms(instance, span):
    if hasattr(instance, "llm"):
        _set_span_attribute(span, SpanAttributes.LLM_TEMPERATURE, instance.llm.temperature)
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MODEL, instance.llm.model_name)
        if hasattr(instance, "prompt"):
            for msg in instance.prompt.messages:
                if msg.__class__.__name__ == "SystemMessage":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.0.system", msg.content)
                elif msg.__class__.__name__ == "HumanMessage":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.0.user", msg.content)
                elif msg.__class__.__name__ == "HumanMessagePromptTemplate":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.0.user", msg.prompt.template)

    return

@_with_tracer_wrapper
def task_wrapper(tracer, to_wrap, wrapped, instance, args, kwargs):
    """Instruments and calls every function defined in TO_WRAP."""
    if context_api.get_value(_SUPPRESS_INSTRUMENTATION_KEY):
        return wrapped(*args, **kwargs)

    # Some Langchain objects are wrapped elsewhere, so we ignore them here
    if instance.__class__.__name__ in ("AgentExecutor"):
        return wrapped(*args, **kwargs)

    if hasattr(instance, "name"):
        name = f"{to_wrap.get('span_name')}.{instance.name.lower()}"
    elif to_wrap.get("span_name"):
        name = to_wrap.get("span_name")
    else:
        name = f"langchain.task.{instance.__class__.__name__}"
    kind = to_wrap.get("kind") or TraceloopSpanKindValues.TASK.value
    with tracer.start_as_current_span(name) as span:
        span.set_attribute(
            SpanAttributes.TRACELOOP_SPAN_KIND,
            kind,
        )
        span.set_attribute(SpanAttributes.TRACELOOP_ENTITY_NAME, name)

        # extract llm parms
        print("otel-task-wrapper")
        # _extract_llm_parms(instance, span)
        print(f"{instance.__class__.__name__}\n")
        printClassDetails(instance)

        return_value = wrapped(*args, **kwargs)
    print(return_value)
    
    return return_value
