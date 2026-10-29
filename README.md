# Classroom Sync — 3D 美术课件多人协作服务（演示版）

提供：课堂创建、每组独立邀请码、无账号学生加入、教师查看指定组、WebSocket 实时同步（新增/移动旋转缩放/改色/删除）、在线人数、健康检查、CloudBase Dockerfile。另附不依赖 3D 框架的浏览器同步测试页面。

> **重要限制：这是可运行的联调演示，不是完成的课堂生产系统。** 所有课堂、令牌、场景均保存在单个 Python 进程内存中。容器重启、升级、缩容时会丢失；多实例之间不会共享状态，正式使用必须接入 CloudBase 数据库、共享消息系统/实时服务，完善监控与访问控制。暂时只允许部署**单实例测试**，不要用于正式保存学生成果。

## 1. 本地运行（Windows PowerShell）

安装 Python 3.12，然后在此目录执行：

```powershell
python -m pip install -r requirements.txt
$env:TEACHER_ADMIN_KEY = "请替换为至少16位的随机私密字符串"
$env:PORT = "3000"
python -m app.server
```

打开 `http://localhost:3000`。在教师创建课堂表单输入刚才设置的管理密钥。生成每组的邀请码后，分别用两个浏览器窗口输入**同一组**的邀请码，验证物体操作实时同步。

## 2. 上传 GitHub

建议创建全新独立仓库：`classroom-sync`；将**本目录所有文件**上传到仓库根目录（Dockerfile 必须在根目录），不要上传包含真实密钥的 `.env` 文件。无需更改原有 `niko` 3D课件仓库。

## 3. CloudBase「新建 Git 平台部署」填写

- Git 仓库：你新建的 `classroom-sync` 仓库
- 服务名称：`classroom-sync`
- 自动部署：第一次建议关闭
- 访问端口 / 容器监听端口：**3000**
- 目标目录：**根目录（留空或 `.`，以控制台提示为准）**
- Dockerfile：**有**，文件名 `Dockerfile`
- 环境变量：`TEACHER_ADMIN_KEY` 设置为**自己生成的至少32位随机密钥**，切勿把它提交到 GitHub
- 环境变量：`PORT=3000`（Dockerfile 亦已设置默认值）
- `ALLOWED_ORIGINS`：测试时留空；发布到 EdgeOne 时填允许的前端来源，如 `https://xxx.edgeone.app`。如同时使用云托管提供的测试页面，请连同云托管页面来源一起填写，用英文逗号分隔。

在创建任何付费资源前，请先确认 **云托管计费模式、实例数、最小实例数、资源上限**。测试期保持单实例，不要设置自动扩展到多个实例，因为内存版本不会跨实例同步。具体 UI 取决于当前 CloudBase 控制台。

## 4. 部署后核验

假设腾讯云托管分配地址为 `https://你的真实域名`：

1. 浏览器打开 `https://你的真实域名/healthz`，应返回 `{ "ok": true, "service":"classroom-sync", "persistence":"memory-only" }`。
2. 浏览器打开 `https://你的真实域名/`，进入示例联调页面。
3. 打开两个窗口，用同组邀请码加入。新增纸盒、改变位置或颜色，应在两个窗口同时出现。
4. WebSocket 地址为 `wss://你的真实域名/ws`（请使用云托管真实域名，不是文档中的占位文本）。

官方参考：https://docs.cloudbase.net/run/develop/access/websocket

## 5. 接入 EdgeOne 现有3D课件

先查看 `docs/protocol.md`。现有课件需要在建模事件中调用 WebSocket `op` 消息：
- 创建模型：`object.add`
- 移动、旋转、缩放：`object.transform`
- 修改颜色：`object.color`
- 删除模型：`object.remove`

服务端广播统一修订版本（revision），客户端以服务器广播为准，重连后重新获取 snapshot。客户端不要逐帧推送鼠标位置或动画，每秒每个连接最多 20 条操作消息。**同一物体同时编辑采用服务器接收顺序最后写入获胜，不是 CRDT 或精细的协同锁。**

## 6. 正式投入课堂前还缺什么？

1. CloudBase 数据库：存储课堂、分组、学生作品和最新场景快照；需要可恢复和备份。
2. 多实例广播：用支持 Redis Pub/Sub、数据库实时服务或其他可扩展消息层，而不是内存 `clients`。
3. 教师身份与邀请码生命周期：目前教师用管理密钥/教师凭证，学生用邀请码，需加过期、撤销、审计及教学合规保护。
4. 更精细的协作：对象锁、修改冲突提示、撤销、历史版本和离线恢复。
5. 稳定性验证：微信/手机端弱网测试，EdgeOne 的跨域规则、浏览器 WebSocket 心跳、云托管费用与伸缩策略。

学校课堂使用应避免输入学生真实姓名和个人敏感数据，测试统一使用昵称。

## 7. 可复用的浏览器客户端

`integration/classroom-sync-client.js` 提供带自动重连的通用浏览器客户端；`integration/threejs-example.js` 给出将操作映射到 Three.js 物体的演示。需要根据现有课件的对象类型、材质体系和渲染逻辑调整，不能直接覆盖已有课件代码。
