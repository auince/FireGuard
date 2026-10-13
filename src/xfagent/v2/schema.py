from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from .config import today

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Actor(Strict):
    user_id: str
    role: Literal['inspector','reviewer','admin']
    projects: list[str]

class InspectionInput(Strict):
    query: str = Field(default='请核查消防隐患及相关法规', min_length=1, max_length=2000)
    image: str | None = Field(default=None, max_length=22000000)
    facility: Literal['indoor_hydrant','outdoor_hydrant','fire_extinguisher','auto'] = 'auto'
    project_id: str = Field(default='default', pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    session_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    jurisdiction: Literal['四川','全国'] = '四川'
    as_of: date = Field(default_factory=lambda:date.fromisoformat(today()))
    scene: dict = Field(default_factory=dict)
    mode: Literal['inspection','retrieval','annotation'] = 'inspection'
    retrieval_mode: Literal['bm25','dense','rrf','rerank','hyde'] = 'rrf'
    query_strategy: Literal['standard','multi'] = 'standard'
    use_model: bool = True

    @field_validator('scene')
    @classmethod
    def bounded_scene(cls,v):
        import json
        if len(json.dumps(v,ensure_ascii=False))>8000:raise ValueError('scene exceeds 8000 characters')
        return v

class Review(Strict):
    expected_revision: int = Field(ge=1)
    action: Literal['approve','return','reject']
    comment: str = Field(default='',max_length=3000)
    conclusions: list[dict] | None = Field(default=None,max_length=20)
    confirmed_scene: dict = Field(default_factory=dict)

    @field_validator('conclusions')
    @classmethod
    def valid_conclusions(cls, values):
        if values is None:return None
        return [Conclusion.model_validate(x).model_dump() for x in values]

    @field_validator('confirmed_scene')
    @classmethod
    def valid_scene(cls, value):
        value=InspectionInput.bounded_scene(value)
        from .fact_checks import numeric_scene,UNITS
        for key in UNITS:
            if key in value:numeric_scene(value,key)
        return value

class Feedback(Strict):
    run_id: str
    signal: Literal['like','dislike','correction','follow_up','copy','verifier_failure','timeout']
    text: str = Field(default='',max_length=4000)
    category: Literal['intent','vision','retrieval','applicability','generation','knowledge_gap'] | None = None

class Strategy(Strict):
    name: str = Field(min_length=1,max_length=100)
    kind: Literal['skill','hook','rule'] = 'skill'
    trigger_terms: list[str] = Field(default_factory=list,max_length=20)
    facilities: list[Literal['indoor_hydrant','outdoor_hydrant','fire_extinguisher']] = Field(default_factory=list)
    expand_terms: list[str] = Field(default_factory=list,max_length=12)
    evidence_k: int = Field(default=5,ge=1,le=8)
    parent_expand: bool = False
    template: Literal['standard','measurement_required','version_conflict','risk_action_evidence'] = 'standard'
    hook: Literal['none','after_rewrite','before_draft'] = 'none'
    require_fields: list[Literal['building_use','building_height','measured_width','pressure_measurement','required_quantity']] = Field(default_factory=list)
    source_feedback_ids: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def policy_boundary(self):
        if self.kind=='hook' and self.hook=='none':raise ValueError('Hook 必须选择白名单节点')
        if self.kind=='hook' and self.hook=='before_draft' and (self.expand_terms or self.parent_expand or self.evidence_k!=5):
            raise ValueError('before_draft Hook 只能调整模板和补充条件')
        if self.kind=='rule' and (not self.require_fields or self.expand_terms or self.parent_expand or self.evidence_k!=5):
            raise ValueError('Rule 只允许管理员审核的补充条件约束')
        return self

class Observation(Strict):
    observation_id: str
    image_id: str | None = None
    facility: str
    status: Literal['visible_anomaly','no_visible_anomaly','uncertain']
    description: str
    labels: list[str] = Field(default_factory=list)
    region: list[float] | None = None
    source: Literal['vlm','detector','human'] = 'vlm'

class Conclusion(Strict):
    claim_id: str = Field(min_length=1,max_length=100)
    text: str = Field(max_length=3000)
    recommendation: str = Field(default='',max_length=2000)
    observation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    applicability: Literal['supported','unknown','not_applicable'] = 'unknown'
    sufficiency: Literal['sufficient','insufficient'] = 'insufficient'
    missing_fields: list[str] = Field(default_factory=list)
    kind: Literal['observation','legal_assessment','information_request']
