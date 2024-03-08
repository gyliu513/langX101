import os, logging
from dotenv import load_dotenv

from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Milvus
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import CharacterTextSplitter
from langchain.chains import RetrievalQA
from langchain_community.document_loaders import TextLoader

from opentelemetry import trace
from traceloop.sdk import Traceloop
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.watsonx import WatsonxInstrumentor

from ibm_watsonx_ai.foundation_models.utils.enums import ModelTypes
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
from ibm_watsonx_ai.foundation_models.utils.enums import DecodingMethods

from ibm_watsonx_ai.foundation_models.extensions.langchain.llm import WatsonxLLM
from ibm_watsonx_ai.foundation_models import Model

from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,

)


FORMAT = '%(asctime)s - %(filename)s:%(lineno)s - %(levelname)s: %(message)s'
logging.basicConfig(
    format=FORMAT,
    level=logging.DEBUG,  ## impect log level in slack sdk
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True
)

logger = logging.getLogger()

load_dotenv()

# """ only need 2 lines code to instrument Langchain LLM
# """
# from otel_lib.instrumentor import LangChainHandlerInstrumentor as SimplifiedLangChainHandlerInstrumentor
# tracer_provider, meter_provider, log_provider = SimplifiedLangChainHandlerInstrumentor().instrument(
#     otlp_endpoint=os.environ["OTLP_EXPORTER_HTTP"],
#     metric_endpoint=os.environ["OTEL_METRICS_EXPORTER"],
#     log_endpoint=os.environ["OTEL_METRICS_EXPORTER"],
#     service_name=os.environ["SVC_NAME"],
#     insecure = True,
#     )
# """=======================================================
# """

Traceloop.init(api_endpoint=os.environ["OTLP_EXPORTER_HTTP"],
               app_name=os.environ["SVC_NAME"],
               )

tracer_provider = TracerProvider(
    resource=Resource.create({'service.name': os.environ["SVC_NAME"]}),
)

# Create an OTLP Span Exporter
otlp_exporter = OTLPSpanExporter(
    endpoint=os.environ["OTLP_EXPORTER_HTTP"],  # Replace with your OTLP endpoint URL
    insecure=True,
)
# trace.set_tracer_provider(tracer_provider)
tracer =trace.get_tracer(__name__)

WatsonxInstrumentor().instrument(tracer_provider=tracer_provider)
            
tracer_provider.add_span_processor(
    SimpleSpanProcessor(otlp_exporter)
)

with tracer.start_as_current_span("sentence embedding"):

    loader = TextLoader("langchain/state_of_the_union.txt")
    documents = loader.load()
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    docs = text_splitter.split_documents(documents)

    # print(f'len of docs = {len(docs)}')
    # print(f'docs[10] = {docs[10].page_content}')

    embeddings = HuggingFaceEmbeddings(
        model_name = 'sentence-transformers/all-mpnet-base-v2'
    )

    vector_db = Milvus.from_documents(
        docs,
        embeddings,
        connection_args={"host": "127.0.0.1", "port": "19530"},
        collection_name="LangChainCollection",
    )

    query = "What did the president say about Ketanji Brown Jackson"
    docs = vector_db.similarity_search(query)

    print(docs[0].page_content)


####################################


    filename = "watsonx/companyPolicies.txt"

    loader = TextLoader(filename)
    documents = loader.load()
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    texts = text_splitter.split_documents(documents)
    print(len(texts))


    embeddings = HuggingFaceEmbeddings()
    docsearch = Milvus.from_documents(texts, embeddings)
    print('documents ingested')


    model_id = ModelTypes.FLAN_UL2
    parameters = {
        GenParams.DECODING_METHOD: DecodingMethods.GREEDY,
        GenParams.MIN_NEW_TOKENS: 130,
        GenParams.MAX_NEW_TOKENS: 200
    }

    logger.debug(f'model_id = {model_id}')

    api_key = os.getenv("WATSONX_APIKEY", None)
    api_endpoint = os.getenv("WATSONX_ENDPOINT", None)
    project_id = os.getenv("WATSONX_PROJECT_ID", None)

    def get_credentials(api_key, api_endpoint):
        return {
            "url" : api_endpoint,
            "apikey" : api_key,
        }

    model = Model(
        model_id=model_id,
        params=parameters,
        credentials=get_credentials(api_key, api_endpoint),
        project_id=project_id
    )

    flan_ul2_llm = WatsonxLLM(model=model)

    qa = RetrievalQA.from_chain_type(llm=flan_ul2_llm, chain_type="stuff", retriever=docsearch.as_retriever())
    query = "mobile policy"
    qa.invoke(query)


