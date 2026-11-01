from langgraph.graph import StateGraph,START
from langchain.messages import HumanMessage
from typing import TypedDict
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from fastapi.responses import StreamingResponse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Annotated
from langgraph.prebuilt.tool_node import ToolNode,tools_condition
import os
from langchain.messages import SystemMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio
import uuid
from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk        
from langchain_core.tools import StructuredTool           

load_dotenv()

model=ChatNVIDIA(model='nvidia/nemotron-3.5-super-vl-120b-a12b')

def clear_all_conversations(checkpointer):

    thread_ids = set()

    for checkpoint in checkpointer.list(None):
        tid = checkpoint.config['configurable']['thread_id']
        thread_ids.add(tid)

    for tid in thread_ids:
        checkpointer.delete_thread(tid)

    print(f"Deleted {len(thread_ids)} previous conversations!")

client = MultiServerMCPClient({
    "web_search_server": {
        "transport": "stdio",
        "command": r"C:\Users\pushk\OneDrive\Desktop\mcp server\myenv\Scripts\python.exe",
        "args": [
            r"C:\Users\pushk\OneDrive\Desktop\mcp server\main.py"
        ]
    }
})

tools = [] 

def make_sync(t):
    return StructuredTool(
        name=t.name,
        description=t.description,
        args_schema=t.args_schema,
        response_format=t.response_format,
        coroutine=t.coroutine,
        func=lambda **kw: asyncio.run(t.coroutine(**kw)),
    )

@asynccontextmanager
async def lifespan(app: FastAPI):

    global tools, model
    raw_tools = await client.get_tools()
    tools = [make_sync(t) for t in raw_tools]
    print("Connected MCP tools:", [tool.name for tool in tools])
    model = model.bind_tools(tools)

    with PostgresSaver.from_conn_string(os.getenv("DATABASE_URL")) as checkpointer:

        print("Connecting to PostgreSQL...")
        checkpointer.setup()
        print("Checkpoint tables created!")

        if os.getenv("CLEAR_ON_START") == "true":
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


SYSTEM_MESSAGE = SystemMessage(
    content="""You are a SYNAPSE AI developed by Pushkar Sinha.
            You have access to real-time external tools, including web search.
            Always use the `web_search` tool when answering questions about current events,
            today's news, live data, or information beyond your knowledge cutoff."""
)

def generate_thread_id():
    thread_id=uuid.uuid4()
    return thread_id

class Chat(TypedDict):
    messages:Annotated[list,add_messages]

def work():
    graph=StateGraph(Chat)

    graph.add_node('chat',chat)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "chat")
    graph.add_conditional_edges("chat", tools_condition)
    graph.add_edge("tools", "chat")

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
        seen_tools = set() 
        for chunk in app.state.chatbot.stream(
            {"messages": [HumanMessage(content=input)]},
            config=CONFIG,
            stream_mode="messages",
            version="v2"
        ):
            if chunk["type"] == "messages":
                message_chunk, metadata = chunk["data"]
                if isinstance(message_chunk, AIMessageChunk):
                    for tc in (message_chunk.tool_call_chunks or []):
                        name = tc.get("name")
                        if name and name not in seen_tools:  
                            seen_tools.add(name)
                            yield f"[[TOOL:{name}]]"
                    if message_chunk.content:
                        yield message_chunk.content


    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8",headers={"X-Thread-ID": thread_id})