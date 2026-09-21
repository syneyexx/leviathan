REMEDIATION_GUIDE = {22: ("SSH exposed", "Use keys and fail2ban.")}
GENERIC_REMEDIATION = ("Unknown", "Restrict and patch.")
def get_remediation(port, service=""):
    return REMEDIATION_GUIDE.get(port, GENERIC_REMEDIATION)
def get_remediation_text(port, service=""):
    return get_remediation(port, service)[1]
