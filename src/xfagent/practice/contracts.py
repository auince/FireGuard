import base64
import io
from datetime import date
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

FACILITIES = {'indoor_hydrant': '室内消火栓', 'outdoor_hydrant': '室外消火栓',
              'fire_extinguisher': '灭火器'}


class Inspection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=2000)
    facility: Literal['auto', 'indoor_hydrant', 'outdoor_hydrant', 'fire_extinguisher'] = 'auto'
    image: str | None = Field(default=None, max_length=14_000_000)
    as_of: date = Field(default_factory=date.today)
    jurisdiction: Literal['四川', '全国'] = '四川'
    scene: dict = Field(default_factory=dict)
    session_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    project_id: str = Field(default='practice', pattern=r'^[a-zA-Z0-9_-]{1,64}$')

    @field_validator('query')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请输入巡检问题')
        return value.strip()

    @field_validator('image')
    @classmethod
    def valid_image(cls, value):
        if value is None:
            return value
        if not value.startswith(('data:image/jpeg;base64,', 'data:image/png;base64,')):
            raise ValueError('仅支持 JPEG / PNG 照片')
        try:
            raw = base64.b64decode(value.split(',', 1)[1], validate=True)
            if len(raw) > 10 * 1024 * 1024:
                raise ValueError('照片不得超过 10MiB')
            with Image.open(io.BytesIO(raw)) as im:
                if im.width * im.height > 16_000_000 or im.format not in {'JPEG', 'PNG'}:
                    raise ValueError('照片尺寸过大或格式不符')
                im.verify()
        except Exception as exc:
            raise ValueError('无效照片或照片超过限制') from exc
        return value

    @field_validator('scene')
    @classmethod
    def bounded_scene(cls, value):
        import json
        if len(json.dumps(value, ensure_ascii=False).encode()) > 8000:
            raise ValueError('现场信息过长')
        return value


class Hazard(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    hazards: list[Hazard] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=12)
