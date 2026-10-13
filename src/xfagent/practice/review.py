import time


def approval_gate(engine, report):
    if report['status'] != 'pending' or not report.get('verification', {}).get('passed'):
        raise ValueError('证据或验证未通过，请退回补充后重新生成')
    state = dict(report, request={key: report[key] for key in
                     ['query', 'facility', 'image', 'as_of', 'jurisdiction', 'scene', 'project_id', 'session_id']},
                 deadline=time.monotonic()+90, model_calls=0)
    checked = engine.verification(state)
    if not checked['passed']:
        raise ValueError('定稿前复核失败：' + '、'.join(checked['errors']))
    return checked
