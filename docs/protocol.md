# 浏览器 / 3D 课件接入协议

## 创建课堂（教师操作）

`POST /api/classrooms`：Header `Authorization: Bearer <TEACHER_ADMIN_KEY>`，body:

```json
{"title":"独特的建筑物","groupCount":4}
```

返回 `classroomId`, `teacherToken`, `groups[]`，每组都含独立 `inviteCode`。所有密钥仅教师保管，不允许写死在 EdgeOne 前端 JavaScript 中。

## 学生加入

`POST /api/join`：

```json
{"inviteCode":"A2BCD345","displayName":"学生A"}
```

返回 `sessionToken`。教师查看某组的接口是 `POST /api/teacher-join`，body 包含 `classroomId`, `groupId`, `teacherToken`，也返回 `sessionToken`。

## WebSocket

地址 `wss://<实际云托管域名>/ws`。连接成功后首先发：

```json
{"type":"auth","token":"<sessionToken>"}
```

服务器返回：

```json
{"type":"snapshot","roomId":"...","groupId":"g1","role":"student","name":"学生A","revision":0,"objects":[]}
```

在线人数通知：`{"type":"presence","onlineCount":2}`

### 新增一个纸盒

```json
{"type":"op","opId":"op_a1","action":"object.add","data":{"object":{"id":"box_1","kind":"paper-box","position":[0,0,0],"rotation":[0,0,0],"scale":[1,1,1],"color":"#4f8cff"}}}
```

### 更新移动/旋转/缩放

```json
{"type":"op","opId":"op_a2","action":"object.transform","data":{"id":"box_1","position":[1,2,0],"rotation":[0,0.3,0],"scale":[1,1,1]}}
```

### 改颜色 / 删除

```json
{"type":"op","opId":"op_a3","action":"object.color","data":{"id":"box_1","color":"#ffbb44"}}
{"type":"op","opId":"op_a4","action":"object.remove","data":{"id":"box_1"}}
```

服务端会向本组全部在线客户端广播规范化后的操作：

```json
{"type":"op","opId":"op_a2","action":"object.transform","data":{"id":"box_1","position":[1,2,0],"rotation":[0,0.3,0],"scale":[1,1,1]},"revision":2,"by":"学生A"}
```

客户端更新 Three.js 场景时，应根据 `object.id` 寻找对应 `mesh`，设置 `mesh.position / mesh.rotation / mesh.scale`，以**收到的服务端操作**为准。刷新、断网重连后用最新 `snapshot` 全量重建。对象模型的几何体/贴图资源需要在课件本身预先定义；本协议不上传网格文件或贴图。正式版要配合 CloudBase 存储管理这些资源。

服务器默认允许每组最多250物体、每连接每秒最多20次操作、单条消息最大16KB，适合课堂创作操作同步，不用于逐帧3D渲染同步。
