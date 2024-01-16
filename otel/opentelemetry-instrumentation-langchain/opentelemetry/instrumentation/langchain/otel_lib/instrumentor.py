import os
from typing import Any, Optional

from .tracer import OpenInferenceTracer
from opentelemetry.trace import get_tracer
from opentelemetry.instrumentation.langchain.version import __version__
# from opentelemetry.metrics import (
#     CallbackOptions,
#     Observation,
#     get_meter_provider,
#     set_meter_provider,
# )

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider, Meter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPMetricExporterHTTP

class LangChainHandlerInstrumentor:
    """
    Instruments the OpenInferenceTracer for LangChain automatically by patching the
    BaseCallbackManager in LangChain.
    """

    def __init__(self, handeler: Optional[OpenInferenceTracer] = None) -> None:
        self._handeler = handeler if handeler is not None else OpenInferenceTracer()

    def instrument(self, *args, **kwargs) -> (TracerProvider, MeterProvider):
        try:
            from langchain.callbacks.base import BaseCallbackManager
        except ImportError:
            # Raise a cleaner error if LangChain is not installed
            raise ImportError(
                "LangChain is not installed. Please install LangChain first to use the instrumentor"
            )

        otlp_endpoint = kwargs.get("otlp_endpoint", None)
        metric_endpoint = kwargs.get("metric_endpoint", None)
        service_name = kwargs.get("service_name", None)
        insecure = kwargs.get("insecure", None)
        if otlp_endpoint is None:
            return None, None
        # 
        # otlp_endpoint:str, metric_endpoint:str, service_name:str, insecure:bool
        tracer_provider, metric_provider = self.otel_init(
            otlp_endpoint=otlp_endpoint, 
            metric_endpoint=metric_endpoint,
            service_name=service_name,
            insecure=insecure,
        )
        # tracer_provider = kwargs.get("tracer_provider", None)
        tracer = get_tracer(__name__, __version__, tracer_provider)
        self._handeler.tracer = tracer
        # metric_provider = kwargs.get("metric_provider", None)
        # tracer = get_tracer(__name__, __version__, tracer_provider)
        meter = metric_provider.get_meter(__name__, __version__)
        self._handeler.meter = meter
        self._handeler.metric_provider = metric_provider
        
        source_init = BaseCallbackManager.__init__

        # Keep track of the source init so we can tell if the patching occurred
        self._source_callback_manager_init = source_init

        handeler = self._handeler

        # Patch the init method of the BaseCallbackManager to add the tracer
        # to all callback managers
        def patched_init(self: BaseCallbackManager, *args: Any, **kwargs: Any) -> None:
            source_init(self, *args, **kwargs)
            self.add_handler(handeler, True)

        BaseCallbackManager.__init__ = patched_init
        
        return tracer_provider, metric_provider
        
    def otel_init(self, otlp_endpoint:str, metric_endpoint:str, service_name:str, insecure:bool) -> (TracerProvider, MeterProvider):
        resource=Resource.create(
                {
                    'service.name': service_name, 
                    'service.instance.id': f"{otlp_endpoint}@{service_name}", 
                    'INSTANA_PLUGIN': "llmonitor"
                }
            )
        if insecure is None:
            insecure = True
        if metric_endpoint is None:
            metric_endpoint = otlp_endpoint
        if service_name is None:
            service_name = "default_service_name"
            
        if insecure:
            os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'
        else:
            os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'False'
        
        # Create an OTLP Span Exporter
        otlp_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
        )
        tracer_provider = TracerProvider(
            resource = resource,
        )

        # Add the exporter to the TracerProvider
        # tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))  # Add any span processors you need
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        # Register the trace provider
        trace.set_tracer_provider(tracer_provider)

        # HTTP metric exporter for test only
        metric_http_endpoint=os.environ["METRIC_EXPORTER_HTTP_MY_TESTING"]
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=metric_endpoint)
            # HTTP metric exporter for test only
            # OTLPMetricExporterHTTP(endpoint=metric_http_endpoint)
        )

        # Metrics console output
        console_reader = PeriodicExportingMetricReader(ConsoleMetricExporter())

        metric_provider = MeterProvider(resource=resource, metric_readers=[console_reader, reader])
        # Register the metric provide
        metrics.set_meter_provider(metric_provider)
        
        return tracer_provider, metric_provider
