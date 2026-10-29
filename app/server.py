"""Minimal classroom collaboration server for CloudBase Cloud Run.

Demo limitations: all rooms/scenes live in ONE process's memory; use CloudBase
Database + a distributed pub/sub layer before production or multi-instance use.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import string
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

LOGGER = logging.getLogger("classroom-sync")
ROOT = Path(__file__).resolve().parent.parent
VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VALID_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
CODE_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
OBJECT_KINDS = {"box", "paper-box", "sphere", "cylinder", "roof", "custom"}
MAX_OBJECTS = 250


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def token() -> str:
    return secrets.token_urlsafe(32)


def short_code() -> str:
    return "".join(secrets.choice(CODE_CHARS) for _ in range(8))


def send_error(reason: str) -> dict[str, Any]:
    return {"type": "error", "message": reason}


def valid_vec(value: Any, *, max_abs: float = 1000, nonzero: bool = False) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        return False
    for n in value:
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not (-max_abs <= n <= max_abs):
            return False
        if nonzero and n <= 0:
            return False
    return True


def validated_object(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    obj_id = raw.get("id")
    kind = raw.get("kind", "box")
    pos = raw.get("position", [0, 0, 0])
    rot = raw.get("rotation", [0, 0, 0])
    scale = raw.get("scale", [1, 1, 1])
    color = raw.get("color", "#4f8cff")
    if not isinstance(obj_id, str) or not VALID_ID.fullmatch(obj_id):
        return None
    if kind not in OBJECT_KINDS or not valid_vec(pos) or not valid_vec(rot):
        return None
    if not valid_vec(scale, max_abs=100, nonzero=True):
        return None
    if not isinstance(color, str) or not VALID_COLOR.fullmatch(color):
        return None
    return {"id": obj_id, "kind": kind, "position": pos, "rotation": rot, "scale": scale, "color": color}


def apply_op(group: dict[str, Any], message: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    action = message.get("action")
    data = message.get("data")
    if not isinstance(data, dict):
        return "操作数据必须是对象", None
    objects = group["objects"]
    if action == "object.add":
        obj = validated_object(data.get("object"))
        if not obj:
            return "无效的3D物体参数", None
        if obj["id"] in objects:
            return "物体ID已存在", None
        if len(objects) >= MAX_OBJECTS:
            return "本组物体数量已达上限", None
        objects[obj["id"]] = obj
        applied = {"object": obj}
    elif action in ("object.transform", "object.color", "object.remove"):
        obj_id = data.get("id")
        if not isinstance(obj_id, str) or not VALID_ID.fullmatch(obj_id) or obj_id not in objects:
            return "物体不存在", None
        if action == "object.remove":
            del objects[obj_id]
            applied = {"id": obj_id}
        elif action == "object.color":
            color = data.get("color")
            if not isinstance(color, str) or not VALID_COLOR.fullmatch(color):
                return "颜色必须为#RRGGBB", None
            objects[obj_id]["color"] = color
            applied = {"id": obj_id, "color": color}
        else:
            keys = [k for k in ("position", "rotation", "scale") if k in data]
            if not keys:
                return "没有可更新的变换参数", None
            applied = {"id": obj_id}
            for key in keys:
                value = data[key]
                if not valid_vec(value, max_abs=100 if key == "scale" else 1000, nonzero=key == "scale"):
                    return f"{key}参数不合法", None
                applied[key] = value
            objects[obj_id].update({k: applied[k] for k in keys})
    else:
        return "不支持的操作类型", None
    group["revision"] += 1
    return None, applied


def create_app(*, admin_key: str | None = None, allowed_origins: str | None = None) -> web.Application:
    key = admin_key if admin_key is not None else os.environ.get("TEACHER_ADMIN_KEY", "")
    if len(key) < 16:
        raise RuntimeError("请设置至少16位随机的 TEACHER_ADMIN_KEY 环境变量")
    origins_raw = allowed_origins if allowed_origins is not None else os.environ.get("ALLOWED_ORIGINS", "")
    allowed = {o.strip().rstrip("/") for o in origins_raw.split(",") if o.strip()}

    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        origin = request.headers.get("Origin", "").rstrip("/")
        if origin and allowed and origin not in allowed:
            return web.json_response({"error": "来源域名未授权"}, status=403)
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    app = web.Application(middlewares=[cors_middleware], client_max_size=20 * 1024)
    app["rooms"] = {}
    app["invites"] = {}
    app["sessions"] = {}
    app["admin_key"] = key
    app["allowed_origins"] = allowed

    async def json_payload(request: web.Request):
        try:
            result = await request.json()
            if not isinstance(result, dict):
                raise ValueError("JSON must be an object")
            return result
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text='{"error":"无效的JSON数据"}', content_type="application/json")

    async def index(_: web.Request):
        return web.FileResponse(ROOT / "static" / "index.html")

    async def health(_: web.Request):
        return web.json_response({"ok": True, "service": "classroom-sync", "persistence": "memory-only"})

    async def create_classroom(request: web.Request):
        supplied = request.headers.get("Authorization", "")
        if not supplied.startswith("Bearer ") or not secrets.compare_digest(supplied[7:], app["admin_key"]):
            return web.json_response({"error": "教师管理密钥错误"}, status=401)
        data = await json_payload(request)
        title = str(data.get("title", "美术创作课")).strip()[:50] or "美术创作课"
        try:
            number = int(data.get("groupCount", 4))
        except (TypeError, ValueError):
            return web.json_response({"error": "分组数量无效"}, status=400)
        if not (1 <= number <= 12):
            return web.json_response({"error": "分组数量必须在1至12之间"}, status=400)
        if len(app["rooms"]) >= 30:
            return web.json_response({"error": "演示服务器课堂数量已达上限"}, status=429)
        room_id = secrets.token_hex(6)
        teacher_token = token()
        groups = {}
        used_codes = app["invites"]
        for i in range(1, number + 1):
            code = short_code()
            while code in used_codes:
                code = short_code()
            group_id = f"g{i}"
            groups[group_id] = {"id": group_id, "label": f"第{i}组", "code": code, "objects": {}, "revision": 0, "clients": set()}
            used_codes[code] = (room_id, group_id)
        app["rooms"][room_id] = {"id": room_id, "title": title, "teacherToken": teacher_token, "createdAt": utc_now(), "groups": groups}
        return web.json_response({"classroomId": room_id, "title": title, "teacherToken": teacher_token,
                                  "groups": [{"id": g["id"], "label": g["label"], "inviteCode": g["code"]} for g in groups.values()]}, status=201)

    async def student_join(request: web.Request):
        data = await json_payload(request)
        code = str(data.get("inviteCode", "")).strip().upper()
        name = str(data.get("displayName", "")).strip()[:24]
        if not name or not code or code not in app["invites"]:
            return web.json_response({"error": "邀请码错误或没有填写姓名"}, status=403)
        room_id, group_id = app["invites"][code]
        room = app["rooms"][room_id]
        session = token()
        app["sessions"][session] = {"roomId": room_id, "groupId": group_id, "name": name, "role": "student", "expireAt": time.monotonic() + 12 * 3600}
        return web.json_response({"sessionToken": session, "classroomTitle": room["title"],
                                  "groupLabel": room["groups"][group_id]["label"], "role": "student"})

    async def teacher_join(request: web.Request):
        data = await json_payload(request)
        room_id = str(data.get("classroomId", ""))
        group_id = str(data.get("groupId", ""))
        room = app["rooms"].get(room_id)
        teacher_token = str(data.get("teacherToken", ""))
        if not room or group_id not in room["groups"] or not secrets.compare_digest(teacher_token, room["teacherToken"]):
            return web.json_response({"error": "教师凭证或分组无效"}, status=403)
        session = token()
        app["sessions"][session] = {"roomId": room_id, "groupId": group_id, "name": "教师", "role": "teacher", "expireAt": time.monotonic() + 12 * 3600}
        return web.json_response({"sessionToken": session, "classroomTitle": room["title"],
                                  "groupLabel": room["groups"][group_id]["label"], "role": "teacher"})

    async def broadcast(group, payload):
        data = json.dumps(payload, ensure_ascii=False)
        dead = []
        for peer in list(group["clients"]):
            if peer.closed:
                dead.append(peer)
            else:
                try:
                    await peer.send_str(data)
                except ConnectionError:
                    dead.append(peer)
        for peer in dead:
            group["clients"].discard(peer)

    async def presence(group):
        await broadcast(group, {"type": "presence", "onlineCount": len(group["clients"])})

    async def websocket(request: web.Request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024, receive_timeout=65)
        await ws.prepare(request)
        group = None
        info = None
        try:
            try:
                first = await asyncio.wait_for(ws.receive(), timeout=10)
            except TimeoutError:
                await ws.send_json(send_error("身份验证超时"))
                return ws
            if first.type != WSMsgType.TEXT:
                await ws.send_json(send_error("请先发送auth消息"))
                return ws
            try:
                hello = json.loads(first.data)
            except json.JSONDecodeError:
                hello = None
            if not isinstance(hello, dict) or hello.get("type") != "auth":
                await ws.send_json(send_error("请先发送auth消息"))
                return ws
            info = app["sessions"].get(hello.get("token")) if isinstance(hello.get("token"), str) else None
            if not info or info["expireAt"] < time.monotonic():
                await ws.send_json(send_error("身份验证无效或已过期，请重新加入"))
                return ws
            room = app["rooms"].get(info["roomId"])
            if not room:
                await ws.send_json(send_error("课堂不存在"))
                return ws
            group = room["groups"][info["groupId"]]
            group["clients"].add(ws)
            await ws.send_json({"type": "snapshot", "roomId": info["roomId"], "groupId": info["groupId"],
                                "role": info["role"], "name": info["name"], "revision": group["revision"],
                                "objects": list(group["objects"].values())})
            await presence(group)
            rate = deque()
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                now = time.monotonic()
                while rate and now - rate[0] > 1:
                    rate.popleft()
                if len(rate) >= 20:
                    await ws.send_json(send_error("操作太频繁，请降低发送速率"))
                    continue
                rate.append(now)
                try:
                    body = json.loads(message.data)
                except json.JSONDecodeError:
                    await ws.send_json(send_error("消息不是合法JSON"))
                    continue
                if not isinstance(body, dict) or body.get("type") != "op":
                    await ws.send_json(send_error("不支持的消息类型"))
                    continue
                err, applied = apply_op(group, body)
                if err:
                    await ws.send_json(send_error(err))
                    continue
                op_id = body.get("opId")
                if not isinstance(op_id, str) or not VALID_ID.fullmatch(op_id):
                    op_id = None
                await broadcast(group, {"type": "op", "opId": op_id, "action": body["action"],
                                        "data": applied, "revision": group["revision"], "by": info["name"]})
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            if group is not None:
                group["clients"].discard(ws)
                await presence(group)
            await ws.close()
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/healthz", health)
    app.router.add_post("/api/classrooms", create_classroom)
    app.router.add_post("/api/join", student_join)
    app.router.add_post("/api/teacher-join", teacher_join)
    app.router.add_get("/ws", websocket)
    app.router.add_route("OPTIONS", "/{tail:.*}", lambda _: web.Response(status=204))
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", "3000"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
