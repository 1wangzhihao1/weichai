# 文件路径: server.py
import os
import sys
import json
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 🌟 寻路雷达：把 scenarios 目录加入系统路径，这样才能 import 到咱们的核心引擎
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'scenarios/order_picking')))
from export_sim_data import export_animation_data

app = FastAPI()

# 🛡️ 允许跨域请求（极其重要：没有这个，前端的 Index.html 会被浏览器拦截，报 CORS 错误）
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

@app.get("/api/trigger_vip")
def api_trigger_vip(current_time: float = 0.0): # 接收大屏传来的当前时间
    print("\n" + "📡"*20)
    print(f"📡 [网关] 收到前端插单请求！当前大屏时空坐标: {current_time:.1f} 秒")
    print("📡"*20)
    
    # 1. 干净利落地把参数透传给底层 RL 引擎！让 AI 亲自去处理！
    export_animation_data(trigger_vip=True, current_time=current_time)
    
    # 2. 读取 AI 亲自推演出来的剧本
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
    playbook_path = os.path.join(project_root, "output", "playbooks", "weichai_ai_animation_script.json")
    
    with open(playbook_path, 'r', encoding='utf-8') as f:
        new_playbook = json.load(f)
        
    print("\n✅ [网关] 真正的 AI 调度剧本生成完毕！下发给前端 3D 大屏！\n")
    return {"status": "success", "playbook": new_playbook}

if __name__ == "__main__":
    print("="*80)
    print("🚀 潍柴 AI 孪生调度中枢启动！")
    print("👂 正在监听前端大屏指令... (端口: 9000)")
    print("="*80)
    uvicorn.run(app, host="127.0.0.1", port=9000)