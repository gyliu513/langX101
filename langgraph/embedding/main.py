#!/usr/bin/env python3
"""
LangGraph Agent with Embedding Retrieval

This agent uses LangGraph to create a conversational agent that can:
- Store documents in a vector database
- Retrieve relevant documents using embeddings
- Answer questions based on retrieved context
- Maintain conversation history

Usage:
    uv run main.py
"""

import os
import asyncio
from typing import Dict, List, Any, Optional, TypedDict, Annotated
from datetime import datetime

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

# Type definitions
class AgentState(TypedDict):
    messages: Annotated[List[Any], "The messages in the conversation"]
    context: Annotated[Optional[str], "Context retrieved from vector store"]
    question: Annotated[Optional[str], "The current question being processed"]

class DocumentStore:
    """Manages document storage and retrieval using Chroma vector store"""
    
    def __init__(self, persist_directory: str = "./chroma_db"):
        self.persist_directory = persist_directory
        self.embeddings = OpenAIEmbeddings()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        
        # Initialize or load existing vector store
        # Chroma automatically creates the directory if it doesn't exist
        self.vectorstore = Chroma(
            persist_directory=persist_directory,
            embedding_function=self.embeddings
        )
    
    def add_documents(self, texts: List[str], metadata: Optional[List[Dict]] = None):
        """Add documents to the vector store"""
        if metadata is None:
            metadata = [{"source": f"doc_{i}", "timestamp": datetime.now().isoformat()} 
                       for i in range(len(texts))]
        
        documents = [Document(page_content=text, metadata=meta) 
                    for text, meta in zip(texts, metadata)]
        
        # Split documents into chunks
        split_docs = self.text_splitter.split_documents(documents)
        
        # Add to vector store
        self.vectorstore.add_documents(split_docs)
        print(f"Added {len(split_docs)} document chunks to vector store")
    
    def search(self, query: str, k: int = 5) -> List[Document]:
        """Search for relevant documents"""
        return self.vectorstore.similarity_search(query, k=k)
    
    def get_relevant_context(self, query: str, k: int = 3) -> str:
        """Get relevant context as a formatted string"""
        docs = self.search(query, k=k)
        if not docs:
            return "No relevant documents found."
        
        context_parts = []
        for i, doc in enumerate(docs, 1):
            context_parts.append(f"Document {i}:\n{doc.page_content}")
            if doc.metadata:
                context_parts.append(f"Source: {doc.metadata.get('source', 'Unknown')}")
        
        return "\n\n".join(context_parts)

class EmbeddingAgent:
    """LangGraph Agent with embedding retrieval capabilities"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0.1
        )
        self.document_store = DocumentStore()
        
        # Initialize memory first
        self.memory = MemorySaver()
        
        # Initialize the graph
        self.graph = self._create_graph()
    
    def _create_graph(self) -> StateGraph:
        """Create the LangGraph workflow"""
        
        # Define the nodes
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("retrieve", self._retrieve_context)
        workflow.add_node("generate", self._generate_response)
        
        # Define the edges
        workflow.set_entry_point("retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", END)
        
        return workflow.compile(checkpointer=self.memory)
    
    def _retrieve_context(self, state: AgentState) -> AgentState:
        """Retrieve relevant context from vector store"""
        messages = state["messages"]
        
        # Get the latest user message
        if not messages:
            return state
        
        latest_message = messages[-1]
        if isinstance(latest_message, HumanMessage):
            question = latest_message.content
            state["question"] = question
            
            # Retrieve relevant context
            context = self.document_store.get_relevant_context(question)
            state["context"] = context
            
            print(f"Retrieved context for: {question[:50]}...")
        
        return state
    
    def _generate_response(self, state: AgentState) -> AgentState:
        """Generate response using retrieved context"""
        messages = state["messages"]
        context = state.get("context", "")
        question = state.get("question", "")
        
        # Create system message with context
        system_prompt = f"""You are a helpful AI assistant with access to a knowledge base. 
Use the following context to answer the user's question. If the context doesn't contain 
relevant information, say so and provide a general helpful response.

Context:
{context}

Answer the user's question based on the context above."""
        
        # Create messages for the LLM
        llm_messages = [SystemMessage(content=system_prompt)] + messages
        
        # Generate response
        response = self.llm.invoke(llm_messages)
        
        # Add response to state
        state["messages"].append(response)
        
        return state
    
    async def chat(self, message: str, session_id: str = "default") -> str:
        """Chat with the agent"""
        # Add user message to state
        state = {
            "messages": [HumanMessage(content=message)]
        }
        
        # Run the graph
        result = await self.graph.ainvoke(
            state,
            config={"configurable": {"thread_id": session_id}}
        )
        
        # Get the last AI message
        messages = result["messages"]
        if messages and isinstance(messages[-1], AIMessage):
            return messages[-1].content
        
        return "Sorry, I couldn't generate a response."

def create_sample_documents():
    """Create sample documents for demonstration"""
    documents = [
        {
            "text": """
            LangGraph is a library for building stateful, multi-actor applications with LLMs. 
            It extends the LangChain expression language with the ability to coordinate multiple 
            chains (or actors) across multiple steps in a way that cycles are allowed.
            """,
            "metadata": {"source": "langgraph_intro", "topic": "framework"}
        },
        {
            "text": """
            Embeddings are numerical representations of text that capture semantic meaning. 
            They allow us to find similar documents by comparing their vector representations 
            in high-dimensional space.
            """,
            "metadata": {"source": "embeddings_explanation", "topic": "ai"}
        },
        {
            "text": """
            Vector databases like Chroma store document embeddings and enable efficient 
            similarity search. They are essential for building retrieval-augmented 
            generation (RAG) systems.
            """,
            "metadata": {"source": "vector_databases", "topic": "database"}
        },
        {
            "text": """
            OpenAI provides powerful language models like GPT-3.5-turbo and GPT-4 that 
            can understand and generate human-like text. These models are trained on 
            vast amounts of data and can perform a wide variety of tasks.
            """,
            "metadata": {"source": "openai_models", "topic": "ai"}
        }
    ]
    return documents

async def main():
    """Main function to run the embedding agent"""
    
    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Please set your OpenAI API key:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        return
    
    print("🤖 Initializing LangGraph Agent with Embedding Retrieval...")
    
    # Create agent
    agent = EmbeddingAgent()
    
    # Add sample documents
    print("📚 Adding sample documents to vector store...")
    sample_docs = create_sample_documents()
    agent.document_store.add_documents(
        [doc["text"] for doc in sample_docs],
        [doc["metadata"] for doc in sample_docs]
    )
    
    print("\n💬 Chat with the agent! (Type 'quit' to exit)")
    print("=" * 50)
    
    session_id = "demo_session"
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("👋 Goodbye!")
                break
            
            if not user_input:
                continue
            
            print("🤔 Thinking...")
            response = await agent.chat(user_input, session_id)
            print(f"🤖 Assistant: {response}")
            
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
