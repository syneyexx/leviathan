# NetStrikerAI — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/TechXplorevo/Netstriker.ai](https://github.com/TechXplorevo/Netstriker.ai).

## Install in HADES

1. Build the package:

```bat
python plugins\netstriker-ai\pack_hadesplugin.py --out plugins\netstriker-ai\dist
```

2. HADES → **Plugins** → **ZIP / .HadesPlugin**
3. Approve dependency install when prompted (`python-nmap`, `pydantic`, `email-validator`)
4. Install the system `nmap` binary if you want `scan_local`
5. Enable the plugin when status is Ready

## Tools

| Tool | Purpose |
|------|---------|
| `doctor` | Layout + dependency checks |
| `list_remediation` | Offline port remediation catalog |
| `get_remediation` | Remediation for one port |
| `dpdp_map` | DPDP Act mapping for high/medium/low risk |
| `resolve_target` | DNS/IP resolve + private-target check |
| `scan_local` | Authorized Nmap scan for **private/loopback only** (`authorized=true`) |

`autonomous` is **false**. Public-host scanning requires NetStrikerAI's domain-verification flow and is intentionally not exposed here.
