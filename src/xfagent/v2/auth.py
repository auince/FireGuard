import os
import jwt
from fastapi import HTTPException,Header
from .schema import Actor

def secret():
    value=os.getenv('XF_V2_JWT_SECRET','')
    if len(value)<32:raise RuntimeError('XF_V2_JWT_SECRET must contain at least 32 characters')
    return value

def actor(authorization: str=Header(default='')):
    try:
        scheme,token=authorization.split(' ',1)
        if scheme.lower()!='bearer':raise ValueError('scheme')
        data=jwt.decode(token,secret(),algorithms=['HS256'],audience='xfagent-v2',
                        options={'require':['exp','iat','sub','aud']})
        return Actor(user_id=data['sub'],role=data['role'],projects=data['projects'])
    except (ValueError,KeyError,jwt.PyJWTError):raise HTTPException(401,'需要有效登录凭据')

def access(a,record,write=False):
    if record is None:raise HTTPException(404,'未找到记录')
    if record.get('project_id','default') not in a.projects:raise HTTPException(403,'项目访问被拒绝')
    if a.role=='inspector' and record.get('owner')!=a.user_id:raise HTTPException(403,'无权访问此任务')
    if write and a.role not in ['reviewer','admin']:raise HTTPException(403,'需要复核权限')

def admin(a):
    if a.role!='admin':raise HTTPException(403,'需要管理员权限')
