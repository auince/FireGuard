from fastapi import FastAPI, HTTPException

from . import STAGE
from .contracts import Inspection
from .harness import Harness


def create_app(engine=None):
    app = FastAPI(title='XFAgent 迭代原型', version=str(STAGE))
    app.state.engine = engine

    @app.get('/api/health')
    def health():
        return {'stage': STAGE, 'model': 'xf-qwen3.5-9b', 'scope': 'resume-practice'}

    @app.post('/api/inspect')
    def inspect(body: Inspection):
        try:
            if app.state.engine is None:
                app.state.engine = Harness()
            return app.state.engine.execute(body.model_dump(mode='json'))
        except Exception as exc:
            raise HTTPException(503, '巡检执行失败，请检查法规索引、嵌入服务和 9B 模型服务') from exc

    return app


app = create_app()
