const SECRET =
  /(authorization\s*:\s*bearer\s+)\S+|((?:api[_-]?key|secret|password|passwd|token)\s*[=:]\s*)\S+|\bsk-[A-Za-z0-9]{8,}\b|\bbearer\s+[A-Za-z0-9\-._~+/]{8,}={0,2}/gi;

export function redactText(input: string): string {
  return input.replace(SECRET, (_match, authPrefix?: string, keyPrefix?: string) => {
    if (authPrefix || keyPrefix) return `${authPrefix || keyPrefix}[REDACTED]`;
    return "[REDACTED]";
  });
}
