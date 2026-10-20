
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from fastapi.middleware.cors import CORSMiddleware
from typing import Annotated, TypedDict
import os

app = FastAPI(title="Synapse AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
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
    response = workflow.invoke({
        "chat_history": [HumanMessage(content=request.message)]
    })

    return {
        "response": response["chat_history"][-1].content
    }
