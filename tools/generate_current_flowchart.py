from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "订单分拣仿真与智能调度系统_当前流程图.png"

W, H = 2200, 1400
MARGIN = 46
TITLE_H = 88
BOTTOM_H = 118
GAP = 32
COL_W = (W - MARGIN * 2 - GAP * 3) // 4
COL_H = H - TITLE_H - BOTTOM_H - MARGIN * 2
COL_Y = MARGIN + TITLE_H

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_MONO = "C:/Windows/Fonts/simhei.ttf"


def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


F_TITLE = font(38, True)
F_COL = font(24, True)
F_STEP_TITLE = font(19, True)
F_STEP = font(15)
F_SMALL = font(15)
F_TAG = font(17, True)
F_NOTE = font(17, True)


PALETTE = [
    {"border": "#5A9BD5", "fill": "#F4FAFF", "header": "#DDEEFF", "box": "#FFFFFF"},
    {"border": "#55B88A", "fill": "#F4FFF8", "header": "#DCF5EA", "box": "#FFFFFF"},
    {"border": "#D79342", "fill": "#FFF9EF", "header": "#FCE8C8", "box": "#FFFFFF"},
    {"border": "#C86B9D", "fill": "#FFF6FB", "header": "#F8DDEC", "box": "#FFFFFF"},
]


def rounded(draw, xy, radius, fill, outline, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def diamond(draw, cx, cy, w, h, fill, outline, width=2):
    pts = [(cx, cy - h // 2), (cx + w // 2, cy), (cx, cy + h // 2), (cx - w // 2, cy)]
    draw.polygon(pts, fill=fill, outline=outline)
    draw.line(pts + [pts[0]], fill=outline, width=width)
    return pts


def wrap_text(text, max_px, draw, fnt):
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        current = ""
        for ch in para:
            trial = current + ch
            if draw.textlength(trial, font=fnt) <= max_px:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines


def center_text(draw, xy, text, fnt, fill="#1B1F24", line_gap=4):
    x1, y1, x2, y2 = xy
    max_w = x2 - x1 - 22
    lines = wrap_text(text, max_w, draw, fnt)
    line_h = fnt.getbbox("国")[3] - fnt.getbbox("国")[1] + line_gap
    total_h = line_h * len(lines) - line_gap
    y = y1 + (y2 - y1 - total_h) / 2
    for line in lines:
        tw = draw.textlength(line, font=fnt)
        draw.text((x1 + (x2 - x1 - tw) / 2, y), line, font=fnt, fill=fill)
        y += line_h


def left_text(draw, xy, text, fnt, fill="#1B1F24", line_gap=5):
    x1, y1, x2, y2 = xy
    max_w = x2 - x1
    lines = wrap_text(text, max_w, draw, fnt)
    y = y1
    line_h = fnt.getbbox("国")[3] - fnt.getbbox("国")[1] + line_gap
    for line in lines:
        draw.text((x1, y), line, font=fnt, fill=fill)
        y += line_h


def arrow(draw, start, end, color="#293241", width=3, dashed=False):
    x1, y1 = start
    x2, y2 = end
    if dashed:
        segments = 20
        for i in range(segments):
            if i % 2 == 0:
                xa = x1 + (x2 - x1) * i / segments
                ya = y1 + (y2 - y1) * i / segments
                xb = x1 + (x2 - x1) * (i + 1) / segments
                yb = y1 + (y2 - y1) * (i + 1) / segments
                draw.line((xa, ya, xb, yb), fill=color, width=width)
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=width)
    import math

    ang = math.atan2(y2 - y1, x2 - x1)
    ah = 15
    aw = 8
    p1 = (x2, y2)
    p2 = (x2 - ah * math.cos(ang) + aw * math.sin(ang), y2 - ah * math.sin(ang) - aw * math.cos(ang))
    p3 = (x2 - ah * math.cos(ang) - aw * math.sin(ang), y2 - ah * math.sin(ang) + aw * math.cos(ang))
    draw.polygon([p1, p2, p3], fill=color)


def add_step(draw, x, y, w, h, title, body, color, kind="box"):
    if kind == "diamond":
        diamond(draw, x + w // 2, y + h // 2, w - 20, h - 4, "#FFF7DB", "#D6A21D", 2)
        center_text(draw, (x + 36, y + 10, x + w - 36, y + h - 10), title + "\n" + body, F_STEP, "#222")
    else:
        rounded(draw, (x, y, x + w, y + h), 13, color["box"], color["border"], 2)
        if title:
            draw.text((x + 18, y + 13), title, font=F_STEP_TITLE, fill="#13294B")
            left_text(draw, (x + 18, y + 48, x + w - 18, y + h - 12), body, F_STEP, "#30343A")
        else:
            center_text(draw, (x + 16, y + 8, x + w - 16, y + h - 8), body, F_STEP, "#30343A")
    return (x + w // 2, y + h)


def draw_column(draw, idx, title, subtitle):
    x = MARGIN + idx * (COL_W + GAP)
    color = PALETTE[idx]
    rounded(draw, (x, COL_Y, x + COL_W, COL_Y + COL_H), 18, color["fill"], color["border"], 3)
    rounded(draw, (x + 25, COL_Y + 20, x + COL_W - 25, COL_Y + 72), 24, color["header"], color["border"], 2)
    center_text(draw, (x + 32, COL_Y + 20, x + COL_W - 32, COL_Y + 72), title, F_COL, "#102A43")
    center_text(draw, (x + 30, COL_Y + 78, x + COL_W - 30, COL_Y + 112), subtitle, F_SMALL, "#59636E")
    return x, color


def main():
    img = Image.new("RGB", (W, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    draw.text((W // 2, 30), "订单分拣仿真与智能调度系统：当前项目流程图", font=F_TITLE, fill="#101828", anchor="ma")
    draw.text((W // 2, 82), "更新版：真实订单/库存预处理 + FastAPI 调度仿真服务 + PPO 策略模型 + Vue 3D 数字孪生大屏", font=F_SMALL, fill="#667085", anchor="ma")

    columns = [
        ("① 数据接入与预处理", "从历史 DMS、库存快照和基础 SKU 数据构建可仿真的订单池"),
        ("② 策略模型训练与评估", "PPO 模型训练、规则策略对比、TensorBoard 指标沉淀"),
        ("③ 后端调度与仿真服务", "FastAPI 统一承接订单、库存、调度、仿真与结果数据"),
        ("④ 前端展示与交付输出", "Vue 3 大屏展示仿真进度、3D 数字孪生和算法对比结果"),
    ]
    xs = []
    for i, (t, s) in enumerate(columns):
        xs.append(draw_column(draw, i, t, s))

    flow_centers = []

    x, c = xs[0]
    y = COL_Y + 148
    steps = [
        (118, "原始数据", "DMS 拣选历史数据\n7.1 早/晚库存单元 Excel\n历史订单与 SKU 主数据", "box"),
        (118, "订单导入", "import_july1_picking.py\n或 /orders/upload 接口\n写入订单池与 BOM 明细", "box"),
        (118, "库存快照", "inventory_preprocess.py\n生成 data/inventory 快照\n支持日初与日末库存选择", "box"),
        (118, "订单预处理", "order_preprocessor.py\n可执行订单进入调度\n缺料订单进入异常队列", "box"),
        (104, "预处理输出", "processable_orders\nshortage_orders\npreprocess_stats / 稀缺 SKU", "box"),
    ]
    prev = None
    for h, title, body, kind in steps:
        bottom = add_step(draw, x + 28, y, COL_W - 56, h, title, body, c, kind)
        if prev:
            arrow(draw, prev, (x + COL_W // 2, y - 2))
        prev = bottom
        y += h + 28
    flow_centers.append(prev)

    x, c = xs[1]
    y = COL_Y + 148
    steps = [
        (108, "训练入口", "train_agent_v1.py\nPickingEnv + MaskablePPO\n使用真实订单片段训练", "box"),
        (108, "环境状态", "站台负载、订单处理时长\naction_masks 容量约束\n站台可用时间", "box"),
        (100, "动作决策", "选择目标站台 Action 0-15\nAI / 轮询 / 随机\nleast_load 等规则策略", "box"),
        (120, "奖励函数", "局部拥堵与距离惩罚\n整批 makespan 终结奖励\n目标：更短完工时间\n更少开机站台", "box"),
        (108, "模型与日志", "ppo_masking_model_v6.zip\nTensorBoard 日志\n/model/training_metrics", "box"),
        (100, "离线对比", "compare.py / simpy_verify.py\n固定测试集验证\nAI、轮询、随机策略", "box"),
    ]
    prev = None
    for h, title, body, kind in steps:
        bottom = add_step(draw, x + 28, y, COL_W - 56, h, title, body, c, kind)
        if prev:
            arrow(draw, prev, (x + COL_W // 2, y - 2))
        prev = bottom
        y += h + 24
    flow_centers.append(prev)

    x, c = xs[2]
    y = COL_Y + 148
    steps = [
        (104, "服务启动", "backend/server.py\nUvicorn 端口 8088\nFastAPI 智能排产网关", "box"),
        (108, "纯调度接口", "POST /schedule/dispatch\n生成订单-站台映射\n保存 schedule_results", "box"),
        (118, "仿真接口", "POST /simulation/start\n后台任务加载订单、库存、模型\n自动寻找 active_stations", "box"),
        (118, "SimPy 物理推演", "simpy_dispatch_engine\n站台加工、传送时间、缓冲容量\n生成 DispatchResult 时间线", "box"),
        (100, "任务查询", "GET /simulation/status\nGET /schedule/result\n返回进度与结果", "box"),
        (104, "播放脚本", "GET /simulation/playbook\n输出 timeline、目标站台\n投放、开始、完成时间", "box"),
    ]
    prev = None
    for h, title, body, kind in steps:
        bottom = add_step(draw, x + 28, y, COL_W - 56, h, title, body, c, kind)
        if prev:
            arrow(draw, prev, (x + COL_W // 2, y - 2))
        prev = bottom
        y += h + 24
    flow_centers.append(prev)

    x, c = xs[3]
    y = COL_Y + 148
    steps = [
        (104, "前端入口", "weichai-aps-frontend\nVue 3 + Vite + Element Plus\n接口 baseURL: /api/v1", "box"),
        (104, "控制面板", "输入 batch_no\n选择日初/日末库存快照\n点击启动仿真", "box"),
        (118, "3D 数字孪生", "Factory3D.vue + Three.js\n播放 playbook 时间线\n站台、箱体、传送过程可视化", "box"),
        (112, "算法对比", "AlgorithmResults.vue + ECharts\nAI / 轮询 / 随机策略\n耗时、开机站台、效率提升", "box"),
        (108, "结果沉淀", "comparison_daily_*.json\nhistory_replay_*.json\n性能图、操作手册、汇报材料", "box"),
        (96, "交付输出", "调度结果 JSON\nplaybook 时间线\n策略对比报表", "box"),
    ]
    prev = None
    for h, title, body, kind in steps:
        bottom = add_step(draw, x + 28, y, COL_W - 56, h, title, body, c, kind)
        if prev:
            arrow(draw, prev, (x + COL_W // 2, y - 2))
        prev = bottom
        y += h + 24
    flow_centers.append(prev)

    # Cross-column integration arrows.
    for i in range(3):
        sx = MARGIN + i * (COL_W + GAP) + COL_W
        ex = MARGIN + (i + 1) * (COL_W + GAP)
        y_mid = COL_Y + 565
        arrow(draw, (sx + 5, y_mid), (ex - 5, y_mid), "#344054", 4)

    # Bottom note.
    note_y = H - BOTTOM_H + 24
    rounded(draw, (MARGIN + 160, note_y, W - MARGIN - 160, note_y + 66), 14, "#FFF7ED", "#E59B45", 2)
    note = "核心总结：库存预处理负责筛选可执行订单与异常订单；PPO/规则策略负责输出站台分配 Action；SimPy 负责传送、排队、加工和时间推进；前端负责展示进度、3D 过程和策略对比。"
    center_text(draw, (MARGIN + 190, note_y + 8, W - MARGIN - 190, note_y + 60), note, F_NOTE, "#7A3E00")

    img.save(OUT_PATH)
    jpg_path = OUT_PATH.with_suffix(".jpg")
    img.save(jpg_path, quality=95)
    print(OUT_PATH)
    print(jpg_path)


if __name__ == "__main__":
    main()
