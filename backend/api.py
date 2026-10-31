from langgraph.graph import StateGraph,START,END
from langchain.messages import HumanMessage
from typing import TypedDict
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from fastapi.responses import StreamingResponse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Annotated
import os
from langchain.messages import SystemMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres import PostgresSaver
import uuid
from dotenv import load_dotenv

load_dotenv()


def clear_all_conversations(checkpointer):

    thread_ids = set()

    for checkpoint in checkpointer.list(None):
        tid = checkpoint.config['configurable']['thread_id']
        thread_ids.add(tid)

    for tid in thread_ids:
        checkpointer.delete_thread(tid)

    print(f"Deleted {len(thread_ids)} previous conversations!")

@asynccontextmanager
async def lifespan(app: FastAPI):

    with PostgresSaver.from_conn_string(os.getenv("DATABASE_URL")) as checkpointer:

        print("Connecting to PostgreSQL...")
        checkpointer.setup()
        print("Checkpoint tables created!")
        clear_all_conversations(checkpointer)

        app.state.checkpointer = checkpointer
        app.state.chatbot = work()
        print("LangGraph initialized!")
        yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Thread-ID"],
)

model=ChatNVIDIA(model='nvidia/nemotron-3.5-super-vl-120b-a12b')

SYSTEM_MESSAGE = SystemMessage(
    content="You are a SYNAPSE AI developed by Pushkar Sinha."
)

def generate_thread_id():
    thread_id=uuid.uuid4()
    return thread_id

class Chat(TypedDict):
    messages:Annotated[list,add_messages]

def work():
    graph=StateGraph(Chat)

    graph.add_node('chat',chat)
    graph.add_edge(START,'chat')
    graph.add_edge('chat',END)

    workflow=graph.compile(checkpointer=app.state.checkpointer)

    return workflow

def chat(state:Chat)->Chat:
    messages = [SYSTEM_MESSAGE] + state['messages']
    response=model.invoke(messages)
    return {'messages':[response]}

def load_conversation(thread_id: str = None):

    if thread_id:
        CONFIG = {'configurable': {'thread_id': thread_id}}
        state = app.state.chatbot.get_state(CONFIG)

        if not state or not state.values:
            return []

        return state.values.get('messages', [])

    else:
        chats = {}

        for checkpoint in app.state.checkpointer.list(None):

            tid = checkpoint.config['configurable']['thread_id']

            if tid not in chats:
                messages = load_conversation(tid)

                chats[tid] = {
                    'thread_id': tid,
                    'messages': messages
                }

        return list(chats.values())

@app.get('/')
def home():
    return {'message':'SYNAPSE API WORKING'}

@app.get('/chats')
def get_chats():
    return load_conversation()

@app.get('/chat')
def get_message(input: str,thread_id: str = None):

    print("Current Thread ID:", thread_id)

    if thread_id is None:
        thread_id=str(generate_thread_id())


    CONFIG={'configurable':{'thread_id':thread_id}}

    def generate():
        ai_response = ""
        for chunk in app.state.chatbot.stream(
            {"messages": [HumanMessage(content=input)]},
            config=CONFIG,
            stream_mode="messages",
            version="v2"
        ):
            if chunk["type"] == "messages":
                message_chunk, metadata = chunk["data"]
                if message_chunk.content:
                    ai_response += message_chunk.content
                    yield message_chunk.content 


    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8",headers={"X-Thread-ID": thread_id})