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
  const ratio = workers.match(/(\d+)\s*\/\s*(\d+)/);
  const workersShown = ratio ? `${ratio[1]}/${ratio[2]}` : workers;
  return (
    <footer className="statusbar">
      <div className="left">
        <span>run_leviathan.exe</span>
        <span>LEVIATHAN Backend Host</span>
        <span>{shown}</span>
      </div>
      <div className="center">TARTARIAN INTELLIGENCE INFRASTRUCTURE · KNOWLEDGE INGESTS · REALITY OBEYS · IN AETERNUM</div>
      <div className="right">
        <span>Uptime: {uptime}</span>
        <Metric label="Services" value={services} />
        <Metric label="Workers" value={workersShown} />
        <Metric label="Queue" value={queue} />
      </div>
    </footer>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  const live = value !== "UNMEASURED" && value !== "—";
  return <span>{live ? <i className="dot ok" /> : null}{label}: {value}</span>;
}
