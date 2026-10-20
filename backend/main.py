
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from fastapi.middleware.cors import CORSMiddleware
from typing import Annotated, TypedDict
from fastapi.responses import StreamingResponse
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Synapse AI")


from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://synapseai-blush.vercel.app",
        "https://synapse-6yt10p60g-sinhapushkar047.vercel.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


model = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.environ["GROQ_API_KEY"]
)

class ChatbotState(TypedDict):
    chat_history: Annotated[list, add_messages]

def chat(state: ChatbotState):
    response = model.invoke(state["chat_history"])
    return {"chat_history": [response]}

graph = StateGraph(ChatbotState)
graph.add_node("chat", chat)
graph.add_edge(START, "chat")
graph.add_edge("chat", END)

workflow = graph.compile()

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def home():
    return {"message": "Synapse AI API is running!"}


@app.post("/chat")
def chat_endpoint(request: ChatRequest):

    def generate_response():
        for message_chunk, metadata in workflow.stream(
            {"chat_history": [HumanMessage(content=request.message)]},
            stream_mode="messages"
        ):
            if message_chunk.content:
                yield message_chunk.content

    return StreamingResponse(
        generate_response(),
        media_type="text/plain"
    )

