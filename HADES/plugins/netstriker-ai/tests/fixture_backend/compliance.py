DPDP_MAPPING = {
  'high': {'section': 'S8', 'summary': 'high', 'obligation': 'fix'},
  'medium': {'section': 'S8', 'summary': 'medium', 'obligation': 'plan'},
  'low': {'section': 'S4', 'summary': 'low', 'obligation': 'monitor'},
}
DPDP_DISCLAIMER = 'guidance only'
def add_dpdp_section(risk_label):
    info = DPDP_MAPPING.get(risk_label, DPDP_MAPPING['low'])
    return {**info, 'disclaimer': DPDP_DISCLAIMER}
