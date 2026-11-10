from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.messages import HumanMessage, AIMessageChunk,AIMessage,AnyMessage
from typing import Annotated
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langgraph.graph.message import add_messages
from langchain_core.messages import ToolMessage
import json
from typing import Literal
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.types import interrupt, Command
from psycopg_pool import ConnectionPool
import asyncio
from langchain_core.tools import StructuredTool
from concurrent.futures import ThreadPoolExecutor
from psycopg.rows import dict_row
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres import PostgresSaver
from uuid import uuid4
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import os,sys
from fastapi import Header
from fastapi import FastAPI

#**********************************************************FASTAPI IMPORT*******************************************

app=FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get('/')
def home():
    return {'message':'Synapse API Working'}


#**********************************************************model loading***********************************************

load_dotenv()

model=ChatNVIDIA(model='nvidia/nemotron-3.5-super-vl-120b-a12b')

class Chatbot(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages]

#************************************************************mcp loading**************************************************

client = MultiServerMCPClient(
    {
        "tavily-search": {
            "transport": "http",
            "url": "http://127.0.0.1:8001/mcp"
        }
    }
)

with ThreadPoolExecutor(max_workers=1) as ex:
    raw_tools = ex.submit(asyncio.run, client.get_tools()).result()

tools = []
for tool in raw_tools:

    def make_sync_fn(t):
        def sync_fn(**kwargs):
            return asyncio.run(t.ainvoke(kwargs))
        return sync_fn

    sync_tool = StructuredTool.from_function(
        func=make_sync_fn(tool),
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )
    tools.append(sync_tool)

model=model.bind_tools(tools)

#******************************************************thread id generation***********************************************

def generate_id():
    thread_id = str(uuid4())
    return thread_id

#******************************************************chatbot func********************************************************

def chat(state:Chatbot):

    input=state.messages
    answer=model.invoke(input) 

    return {"messages": [answer]}

#******************************************************tool using permission (HITL)*******************************************************

def approval(state: Chatbot) -> Command[Literal["tools", "chat"]]:
    calls = [{"id": tc["id"], "name": tc["name"], "args": tc["args"]}
             for tc in state.messages[-1].tool_calls]

    decision = interrupt({"tool_calls": calls})
    if decision["approved"]:
        return Command(goto="tools")

    denied = [ToolMessage(content="User denied permission to run this tool.",
                          tool_call_id=c["id"], name=c["name"]) for c in calls]
    return Command(goto="chat", update={"messages": denied})


#********************************************************post gre connection**********************************************

DB_URI = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@localhost:5432/{os.getenv('POSTGRES_DB')}"

pool = ConnectionPool(
    conninfo=DB_URI,
    max_size=10,
    kwargs={"autocommit": True, "row_factory": dict_row}
)

checkpointer = PostgresSaver(pool)
checkpointer.setup()

#***********************************************************graph building*************************************************

graph=StateGraph(Chatbot)

graph.add_node('chat',chat)
graph.add_node("approval", approval) 
graph.add_node("tools", ToolNode(tools))
graph.add_edge(START,'chat')
graph.add_conditional_edges("chat", lambda s: "approval" if s.messages[-1].tool_calls else END) 
graph.add_edge("tools", "chat")

workflow = graph.compile(checkpointer=checkpointer)

#***********************************************************streaming feature************************************************

def stream(payload, config):
    for mode, data in workflow.stream(payload, config=config, stream_mode=["messages", "updates"]):

        if mode == "messages":
            chunk, metadata = data
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                text = chunk.content if isinstance(chunk.content, str) else "".join(b.get('text', "") for b in chunk.content if isinstance(b, dict))
                yield text

        elif mode == "updates" and "__interrupt__" in data:
            for it in data["__interrupt__"]:
                yield f"\n[[APPROVAL:{json.dumps(it.value, default=str)}]]"


#***************************************************************user input**************************************************
@app.get('/Conversation')
def conv(user_input: str, thread_id: str | None = Header(default=None)):
    config = {"configurable": {"thread_id": thread_id or generate_id()}}
    payload = {'messages': [HumanMessage(content=user_input)]}
    return StreamingResponse(stream(payload, config), media_type="text/plain")


@app.get('/Approve')
def approve(approved: bool, thread_id: str = Header()):
    config = {"configurable": {"thread_id": thread_id}}
    return StreamingResponse(stream(Command(resume={"approved": approved}), config), media_type="text/plain")