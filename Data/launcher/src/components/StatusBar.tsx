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
  const shown = version.startsWith("v") ? version : `v${version}`;
  return (
    <footer className="statusbar">
      <div className="left">
        <span>run_leviathan.exe</span>
        <span>LEVIATHAN Backend Host</span>
        <span>{shown}</span>
      </div>
      <div className="center">TARTARIAN INTELLIGENCE INFRASTRUCTURE · KNOWLEDGE INGESTS · REALITY OBEYS · IN AETERNUM</div>
      <div className="right">
        <span>Uptime {uptime}</span>
        <span>Services {services}</span>
        <span>Workers {workers}</span>
        <span>Queue {queue}</span>
      </div>
    </footer>
  );
}
