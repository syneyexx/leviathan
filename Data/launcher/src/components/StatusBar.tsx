export function StatusBar({
  version,
  uptime,
  services,
  workers,
  queue,
}: {
  version: string;
  uptime: string;
  services: string;
  workers: string;
  queue: string;
}) {
  return (
    <footer className="statusbar">
      <div>run_leviathan.exe | LEVIATHAN Backend Host | {version}</div>
      <div className="center">TARTARIAN INTELLIGENCE INFRASTRUCTURE · KNOWLEDGE INCIPIT · QUALITY OBEYS · IN AETERNUM</div>
      <div className="right">
        <span>Uptime {uptime}</span>
        <span>Services {services}</span>
        <span>Workers {workers}</span>
        <span>Queue {queue}</span>
      </div>
    </footer>
  );
}
