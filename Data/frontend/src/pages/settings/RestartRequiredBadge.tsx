import type { SettingState } from "../../types/api";

export function RestartRequiredBadge({ setting }: { setting: SettingState }) {
  if (setting.apply_mode === "bootstrap_only" || setting.source === "locked") {
    return <span className="lv-settings-badge is-locked">ENVIRONMENT</span>;
  }
  if (!setting.editable) {
    return <span className="lv-settings-badge is-locked">READ ONLY</span>;
  }
  if (setting.status === "restart_required" || (setting.restart_required && !setting.effective_now)) {
    return <span className="lv-settings-badge is-restart">RESTART REQUIRED</span>;
  }
  if (setting.apply_mode === "restart_required") {
    return <span className="lv-settings-badge is-restart">RESTART ON CHANGE</span>;
  }
  if (setting.experimental) {
    return <span className="lv-settings-badge is-experimental">EXPERIMENTAL</span>;
  }
  return <span className="lv-settings-badge is-live">LIVE</span>;
}
