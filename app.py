# ============ 第 2 步：导入 + 创建应用 ============
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from tools.player_settings import search_cs_player
from agent.cs_agent import create_query_agent

app = FastAPI(title="CS Pro Settings Agent")

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "database" / "players.db"

# ============ 第 5 步：Agent 单例（放哪都行，建议放接口上面） ============
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = create_query_agent()
    return _agent

# ============ 第 6 步：静态文件（页面） ============
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

@app.get("/")
def index():
    return FileResponse(PROJECT_ROOT / "static" / "index.html")

# ============ 第 3 步：选手列表接口 ============
@app.get("/api/players")
def list_players(q: str = ""):
    conn = sqlite3.connect(DB_PATH)
    try:
        sql = "SELECT nickname, real_name, team FROM players"
        params = []
        if q.strip():
            sql += " WHERE nickname LIKE ? OR real_name LIKE ? OR team LIKE ?"
            like = f"%{q.strip()}%"
            params = [like, like, like]
        sql += " ORDER BY nickname LIMIT 50"
        rows = conn.execute(sql, params).fetchall()
        return {
            "total": len(rows),
            "players": [
                {"nickname": r[0], "real_name": r[1], "team": r[2]}
                for r in rows
            ],
        }
    finally:
        conn.close()

# ============ 第 4 步：单选手接口 ============
@app.get("/api/player/{name}")
def get_player(name: str):
    result = search_cs_player.invoke({"player_name": name})
    if result == "Player not found":
        raise HTTPException(status_code=404, detail="没有找到这名选手")
    return result

# ============ 第 5 步：聊天接口（就是这一段） ============
class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    try:
        result = get_agent().invoke({
            "messages": [{"role": "user", "content": req.message.strip()}]
        })
        return {"answer": result["messages"][-1].content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 调用失败: {e}")