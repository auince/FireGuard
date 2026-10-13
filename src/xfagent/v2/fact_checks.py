"""Deterministic safeguards, complementary to semantic/professional review."""
import math
import re

def condition_matches(value, expected):
    if not isinstance(expected, dict):
        # Python otherwise treats True as 1; legal conditions must be typed.
        return type(value) is type(expected) and value == expected
    if set(expected) == {'all'}:
        return all(condition_matches(value, x) for x in expected['all'])
    if not expected or set(expected) - {'eq', 'in', 'gte', 'gt', 'lte', 'lt'}:
        raise ValueError('unsupported applicability operator')
    for operator, target in expected.items():
        if operator == 'eq':
            if not condition_matches(value, target):return False
        elif operator == 'in':
            if not isinstance(target, list):raise ValueError('in requires a list')
            if not any(condition_matches(value, x) for x in target):return False
        else:
            if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in [value, target]):
                return False
            if not {'gte': value >= target, 'gt': value > target,
                    'lte': value <= target, 'lt': value < target}[operator]:return False
    return True

# Numeric scene fields retain backwards compatibility; structured values add units
# and explicit confirmation. They are user/reviewer supplied, not instrument certified.
UNITS = {'measured_width': {'m': 1, '米': 1, 'cm': .01, '厘米': .01, 'mm': .001, '毫米': .001},
         'pressure_measurement': {'mpa': 1, '兆帕': 1, 'kpa': .001, '千帕': .001, 'pa': .000001},
         'required_quantity': {'个': 1, '具': 1, '台': 1},
         'observed_quantity': {'个': 1, '具': 1, '台': 1}}
PATTERNS = {
    'measured_width': r'(?:净宽|宽度|宽为|通道宽)[^\d，。；\n]{0,12}(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)?',
    'pressure_measurement': r'(?:水压|压力|压强)[^\d，。；\n]{0,12}(\d+(?:\.\d+)?)\s*(MPa|kPa|Pa|兆帕|千帕)?',
}

def numeric_scene(scene, field):
    value = scene.get(field)
    if isinstance(value, dict):
        if value.get('confirmed') is not True:raise ValueError('unconfirmed measurement')
        unit = str(value.get('unit', '')).lower()
        if unit not in UNITS[field]:raise ValueError('missing or unsupported unit')
        number = value.get('value'); scale = UNITS[field][unit]
    else:
        number = value; scale = 1
    if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
        raise ValueError('invalid measurement value')
    if field in {'required_quantity','observed_quantity'} and number != int(number):raise ValueError('quantity must be integral')
    return number * scale

def measurement_checks(claim, scene):
    errors = []; missing = []; text = claim['text']
    for field, pattern in PATTERNS.items():
        for sentence in re.split(r'[，。；\n]', text):
            for match in re.finditer(pattern, sentence, re.I):
                # A quoted normative threshold is not a statement of measurement.
                prefix = sentence[:match.start()] + sentence[match.start():match.start(1)]
                normative = bool(re.search(r'规定|规范|标准|要求|应|须|不得|至少|是否|请|补测', prefix))
                actual = bool(re.search(r'现场|实测|测得|只有|仅有|仅为|实际', sentence))
                if normative and not actual:continue
                if field not in scene:
                    errors.append({'code': 'unmeasured_fact', 'claim_id': claim['claim_id'], 'field': field});missing.append(field);continue
                try:
                    provided = numeric_scene(scene, field)
                    unit = (match.group(2) or ('m' if field == 'measured_width' else 'MPa')).lower()
                    asserted = float(match.group(1)) * UNITS[field][unit]
                    if not math.isclose(provided, asserted, rel_tol=1e-6, abs_tol=1e-9):
                        errors.append({'code': 'measurement_value_mismatch', 'claim_id': claim['claim_id'], 'field': field})
                except (ValueError, KeyError):
                    errors.append({'code': 'invalid_measurement_fact', 'claim_id': claim['claim_id'], 'field': field});missing.append(field)
    if '数量不足' in text:
        quantities={}
        for field in ['required_quantity','observed_quantity']:
            if field not in scene:
                errors.append({'code': 'unmeasured_fact', 'claim_id': claim['claim_id'], 'field': field});missing.append(field)
            else:
                try:quantities[field]=numeric_scene(scene, field)
                except ValueError:
                    errors.append({'code': 'invalid_measurement_fact', 'claim_id': claim['claim_id'], 'field': field});missing.append(field)
        if len(quantities)==2 and quantities['observed_quantity']>=quantities['required_quantity']:
            errors.append({'code':'measurement_value_mismatch','claim_id':claim['claim_id'],'field':'observed_quantity'})
    return errors, missing
