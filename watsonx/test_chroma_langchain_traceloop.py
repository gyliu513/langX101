import os, logging
from dotenv import load_dotenv

from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
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
               app_name=os.environ["CHROMA_SVC"],
               )

tracer_provider = TracerProvider(
    resource=Resource.create({'service.name': os.environ["CHROMA_SVC"]}),
)

# Create an OTLP Span Exporter
otlp_exporter = OTLPSpanExporter(
    endpoint=os.environ["OTLP_EXPORTER_HTTP"],  
    insecure=True,
)

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

    embeddings = HuggingFaceEmbeddings(
        model_name = 'sentence-transformers/all-mpnet-base-v2'
    )

    # # create the open-source embedding function
    # embedding_function = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")


    vector_db = Chroma.from_documents(
        docs,
        embeddings,
    )

    query = "What did the president say about Ketanji Brown Jackson"
    docs = vector_db.similarity_search(query)

    print(docs[0].page_content)

####################################


# RuntimeError: Your system has an unsupported version of sqlite3. Chroma requires sqlite3 >= 3.35.0.
# Please visit https://docs.trychroma.com/troubleshooting#sqlite to learn how to upgrade.

# https://docs.trychroma.com/troubleshooting#sqlite
# https://gist.github.com/defulmere/8b9695e415a44271061cc8e272f3c300
# 
# __import__('pysqlite3')
# import sys
# sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# 
# in file /root/jupyter/virtualenv/slack-dev-3.10/lib/python3.10/site-packages/chromadb/__init__.py

    filename = "watsonx/companyPolicies.txt"

    loader = TextLoader(filename)
    documents = loader.load()
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    texts = text_splitter.split_documents(documents)
    print(len(texts))

    embeddings = HuggingFaceEmbeddings()
    docsearch = Chroma.from_documents(texts, embeddings)
    print('documents ingested')


    model_id = ModelTypes.FLAN_UL2
    parameters = {
        GenParams.DECODING_METHOD: DecodingMethods.GREEDY,
        GenParams.MIN_NEW_TOKENS: 130,
        GenParams.MAX_NEW_TOKENS: 200
    }

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


