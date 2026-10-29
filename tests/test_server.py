"""Run from the repository root with: python -m unittest discover -s tests -v"""
import unittest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer
from app.server import create_app


class CollaborationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = TestServer(create_app(admin_key='my-long-demo-secret-12345'))
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def make_classroom(self, count=2):
        r = await self.client.post('/api/classrooms', json={'title':'纸盒建筑','groupCount':count}, headers={'Authorization':'Bearer my-long-demo-secret-12345'})
        self.assertEqual(r.status, 201)
        return await r.json()

    async def join_student(self, code, name):
        r = await self.client.post('/api/join', json={'inviteCode':code, 'displayName':name})
        self.assertEqual(r.status, 200)
        return (await r.json())['sessionToken']

    async def ws_auth(self, ticket):
        ws = await self.client.ws_connect('/ws')
        await ws.send_json({'type':'auth','token':ticket})
        msg = await ws.receive_json(timeout=3)
        self.assertEqual(msg['type'],'snapshot')
        await ws.receive_json(timeout=3)  # initial presence
        return ws, msg

    async def test_unauthorized_teacher_cannot_create_classroom(self):
        r=await self.client.post('/api/classrooms', json={'title':'X','groupCount':2})
        self.assertEqual(r.status, 401)

    async def test_student_join_and_same_group_broadcast(self):
        classinfo = await self.make_classroom()
        code = classinfo['groups'][0]['inviteCode']
        wa, sa=await self.ws_auth(await self.join_student(code,'学生A'))
        wb, sb=await self.ws_auth(await self.join_student(code,'学生B'))
        self.assertEqual(sa['groupId'], sb['groupId'])
        # B joined, A will receive an updated presence notification.
        peer_msg=await wa.receive_json(timeout=3)
        self.assertEqual(peer_msg['type'],'presence')
        self.assertEqual(peer_msg['onlineCount'],2)
        op={'type':'op','opId':'abc1','action':'object.add','data':{'object':{
            'id':'b1','kind':'paper-box','position':[0,0,0], 'rotation':[0,0,0], 'scale':[1,1,1], 'color':'#4f8cff'}}}
        await wa.send_json(op)
        am=await wa.receive_json(timeout=3)
        bm=await wb.receive_json(timeout=3)
        self.assertEqual(am['type'],'op')
        self.assertEqual(bm['action'],'object.add')
        self.assertEqual(bm['revision'],1)
        await wb.send_json({'type':'op','opId':'op2','action':'object.transform','data':{'id':'b1','position':[4,2,0]}})
        moveda=await wa.receive_json(timeout=3)
        movedb=await wb.receive_json(timeout=3)
        self.assertEqual(moveda['data']['position'],[4,2,0])
        self.assertEqual(movedb['revision'],2)
        # newly joining peer gets latest state snapshot
        wc, sc=await self.ws_auth(await self.join_student(code,'学生C'))
        self.assertEqual(sc['objects'][0]['position'],[4,2,0])
        self.assertEqual(sc['revision'],2)
        await wc.close();await wb.close();await wa.close()

    async def test_isolation_and_teacher_view(self):
        classinfo=await self.make_classroom()
        code1=classinfo['groups'][0]['inviteCode']
        code2=classinfo['groups'][1]['inviteCode']
        student1,snapshot1=await self.ws_auth(await self.join_student(code1,'甲'))
        student2,snapshot2=await self.ws_auth(await self.join_student(code2,'乙'))
        self.assertNotEqual(snapshot1['groupId'],snapshot2['groupId'])
        teacher_resp=await self.client.post('/api/teacher-join',json={
            'classroomId':classinfo['classroomId'], 'groupId':'g1', 'teacherToken':classinfo['teacherToken']})
        self.assertEqual(teacher_resp.status,200)
        teacher,_=await self.ws_auth((await teacher_resp.json())['sessionToken'])
        extra=await student1.receive_json(timeout=3)
        self.assertEqual(extra['type'],'presence')
        await student1.send_json({'type':'op','opId':'x1','action':'object.add','data':{'object':{
            'id':'x1','kind':'box','position':[0,0,0],'rotation':[0,0,0],'scale':[1,1,1],'color':'#112233'}}})
        self.assertEqual((await student1.receive_json(timeout=3))['type'],'op')
        self.assertEqual((await teacher.receive_json(timeout=3))['type'],'op')
        # Other group has independent scene/revision.
        self.assertEqual(self.server.app['rooms'][classinfo['classroomId']]['groups']['g2']['revision'],0)
        await teacher.close();await student1.close();await student2.close()

    async def test_health_and_reject_bad_object(self):
        health=await self.client.get('/healthz')
        self.assertEqual((await health.json())['persistence'], 'memory-only')
        c=await self.make_classroom(count=1)
        ws,_=await self.ws_auth(await self.join_student(c['groups'][0]['inviteCode'],'A'))
        await ws.send_json({'type':'op','action':'object.add','data':{'object':{'id':'bad','scale':[-1,0,2]}}})
        self.assertEqual((await ws.receive_json(timeout=3))['type'],'error')
        await ws.close()


if __name__ == '__main__':
    unittest.main()
