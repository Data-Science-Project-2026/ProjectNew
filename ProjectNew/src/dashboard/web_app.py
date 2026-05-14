from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import psycopg2

app = FastAPI()

# 允许 Metabase 页面（localhost:3000）去请求你的 API（可选，但建议）
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # 允许所有端口（包括你现在的 8080）访问
    allow_credentials=False,       # 当 origins 为 "*" 时，必须为 False
    allow_methods=["*"],
    allow_headers=["*"],
)

# 修改前
# GRAPH_HTML_PATH = os.path.join(os.path.dirname(__file__), "graph.html")

# 修改后：明确指向 html 子文件夹
BASE_DIR = os.path.dirname(__file__)
HTML_DIR = os.path.join(BASE_DIR, "html")
GRAPH_HTML_PATH = os.path.join(HTML_DIR, "graph.html")
MODIFIES_HTML_PATH = os.path.join(HTML_DIR, "species_modifies.html")

def get_conn():
    # 统一连接到你在 docker-compose 里新定义的数据库
    return psycopg2.connect(
        host=os.getenv("PGHOST", "db"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname="dashboard_database",  # 改为新的数据库名
        user="dashboard",             # 改为新用户名
        password="dashboard",         # 改为新密码
    )

def get_conn_species():
    # 这里的逻辑和上面一致，因为你的所有表现在都在一个库里
    return get_conn()

def add_iframe_headers(resp):
    # MutableHeaders 没有 pop，用 del
    if "x-frame-options" in resp.headers:
        del resp.headers["x-frame-options"]

    # 如果之前设置过 CSP frame-ancestors，也可以删掉/重设
    if "content-security-policy" in resp.headers:
        del resp.headers["content-security-policy"]

    # 允许被 iframe 嵌入（按需限制来源）
    # 注意：frame-ancestors 建议写你的 metabase 域名；本机可先用 http://localhost:3000
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'self' http://localhost:3000"

    return resp


@app.get("/graph.html")
def serve_graph_html():
    with open(GRAPH_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    resp = HTMLResponse(html)
    return add_iframe_headers(resp)

MAP_HTML_PATH = os.path.join(os.path.dirname(__file__), "species_map.html")


@app.get("/species_modifies.html")
def serve_species_modifies():
    with open(MODIFIES_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    resp = HTMLResponse(html)
    return add_iframe_headers(resp) # 必须调用这个函数注入 Headers

@app.get("/animals")
def animals():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source FROM cooccur_edges ORDER BY 1;")
        return [r[0] for r in cur.fetchall()]

@app.get("/graph")
def graph(animal: str = "panda"):
    with get_conn() as conn, conn.cursor() as cur:
        # edges: 只取这个 animal 的邻居（plant/emotion）
        cur.execute(
            "SELECT source, target, weight, target_type FROM cooccur_edges WHERE source=%s ORDER BY weight DESC;",
            (animal,),
        )
        edges = cur.fetchall()

        # node types（从 cooccur_nodes 查）
        cur.execute("SELECT id, type FROM cooccur_nodes;")
        type_map = {i: t for (i, t) in cur.fetchall()}

    # build nodes
    nodes = []
    # center node
    nodes.append({"id": animal, "type": "animal", "value": 1.0})
    # neighbor nodes
    seen = set([animal])
    for s, t, w, tt in edges:
        if t not in seen:
            nodes.append({"id": t, "type": type_map.get(t, tt), "value": float(w)})
            seen.add(t)

    links = [{"source": s, "target": t, "value": float(w), "target_type": tt} for (s, t, w, tt) in edges]
    return {"center": animal, "nodes": nodes, "links": links}

@app.get("/api/species")
def get_species(city: str = Query(None)):
    with get_conn_species() as conn, conn.cursor() as cur:
        # 修改后的 SQL：
        # 1. 提取属名 (genus)
        # 2. 关联 species_details 获取 category ID
        # 3. 关联 category_list 获取 kingdom 和 category 名称
        query = """
            SELECT DISTINCT ON (i.post_id) 
                p.city_en, 
                p.latitude, 
                p.longitude, 
                split_part(s.species, ' ', 1) AS genus,
                cl.category AS category_name,
                cl.kingdom
            FROM image_species s 
            JOIN images i ON s.image_id = i.id 
            JOIN posts po ON i.post_id = po.id 
            JOIN parks_with_coordinates p ON po.park = p.park_name_in_post
            -- 关键关联 --
            JOIN species_details sd ON split_part(s.species, ' ', 1) = sd.scientific_name
            JOIN category_list cl ON sd.category = cl.id
            --------------
            WHERE s.confidence > 0.4 
        """
        
        params = []
        if city:
            query += " AND p.city_en = %s"
            params.append(city)

        #query += " ORDER BY i.post_id, s.confidence DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

    # 构建返回给前端的 JSON
    data = [
        {
            "city": r[0],
            "lat": float(r[1]),
            "lng": float(r[2]),
            "genus": r[3],    # 新增
            "category": r[4], # 新增
            "kingdom": r[5]   # 新增
        }
        for r in rows
    ]

    return JSONResponse(data)

