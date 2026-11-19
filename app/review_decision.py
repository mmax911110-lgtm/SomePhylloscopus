"""Present independent diagnoses without turning disagreement into a correction.

No labels, thresholds, file names or training-example identities are consulted.
An agreement is a model agreement, never an independently confirmed species.
"""


def species_decision(box):
    expert=box.get('specialist') or {}
    original=box.get('original_scientific_name')
    specialist=expert.get('scientific_name')
    eligible=box.get('gate_status')=='willow' and bool(expert)
    if eligible and original and specialist and original!=specialist:
        return {'status':'disagreement','confirmed_species':None,
            'original_scientific_name':original,'specialist_scientific_name':specialist,
            'message':'原判与专项有分歧，种类待确认。原判：'+str(box.get('original_name')or original)+
                '；专项：'+str(expert.get('common_name')or specialist)+'。',
            'automatic_override':False}
    if eligible and original and original==specialist:
        return {'status':'agreement','confirmed_species':None,
            'original_scientific_name':original,'specialist_scientific_name':specialist,
            'message':'两路预测一致，仍需结合原图确认。','automatic_override':False}
    return {'status':'unreviewed','confirmed_species':None,
        'original_scientific_name':original,'specialist_scientific_name':specialist,
        'message':'专项未形成可比较的鸟种结果，保留原判。','automatic_override':False}


def has_disagreement(result):
    return any(species_decision(box)['status']=='disagreement'for box in(result or {}).get('boxes',[]))
