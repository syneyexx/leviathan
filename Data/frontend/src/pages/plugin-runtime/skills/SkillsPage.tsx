import { AppShell } from "../../../layouts/AppShell";
import { SkillsHero, SkillsKpiStrip } from "./components/SkillsHero";
import { SkillLibrary } from "./components/SkillLibrary";
import {
  SkillActions,
  SkillDetailHeader,
  SkillDetailTabs,
  SkillInfoCards,
  SkillWorkspace,
} from "./components/SkillDetail";
import { useSkillsPage } from "./hooks/useSkillsPage";
import "../../../styles/plugin-runtime-skills.css";

export function SkillsPage() {
  const vm = useSkillsPage();

  return (
    <AppShell
      modeLabel="Plugin Mode"
      searchPlaceholder="Search skills, capabilities..."
      systemItems={["Skills", "Agents", "Tools", "Knowledge"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime lv-app--skills"
    >
      <main className="lv-main lv-pr-main lv-sk-main">
        <SkillsHero />
        <SkillsKpiStrip items={vm.kpis} />

        <section className="lv-sk-body">
          <SkillLibrary
            chips={vm.chips}
            filter={vm.filter}
            onFilter={vm.changeFilter}
            query={vm.queryInput}
            onQuery={vm.setQueryInput}
            skills={vm.skills}
            selectedId={vm.selectedId}
            onSelect={vm.selectSkill}
            loading={vm.loading}
            error={vm.error}
            offset={vm.offset}
            limit={vm.PAGE_LIMIT}
            onPrev={() => vm.setOffset(Math.max(0, vm.offset - vm.PAGE_LIMIT))}
            onNext={() => vm.setOffset(vm.offset + vm.PAGE_LIMIT)}
            onRefresh={() => void vm.reload()}
          />

          <div className="lv-sk-detail" aria-label="Selected skill">
            {vm.skill ? (
              <>
                <SkillDetailHeader skill={vm.skill} />
                <SkillActions
                  actions={vm.actions}
                  busy={vm.actionBusy}
                  moreOpen={vm.moreOpen}
                  onMoreToggle={() => vm.setMoreOpen(!vm.moreOpen)}
                  onAction={(id) => {
                    void (async () => {
                      switch (id) {
                        case "execute":
                          await vm.onExecute();
                          break;
                        case "configure":
                          await vm.onConfigure();
                          break;
                        case "test":
                          await vm.onTest();
                          break;
                        case "examples":
                          await vm.onViewExamples();
                          break;
                        case "disable":
                          await vm.onToggleEnabled();
                          break;
                        case "update":
                          await vm.onUpdate();
                          break;
                        case "load_instructions":
                          await vm.loadInstructions();
                          vm.setMoreOpen(false);
                          break;
                        case "logs":
                          await vm.onLoadModuleLogs();
                          vm.setTab("logs");
                          vm.setMoreOpen(false);
                          break;
                        case "versions":
                          await vm.onLoadVersions();
                          vm.setTab("version_history");
                          vm.setMoreOpen(false);
                          break;
                        default:
                          break;
                      }
                    })();
                  }}
                />
                <SkillInfoCards skill={vm.skill} infoFields={vm.infoFields} />
                <SkillDetailTabs
                  tab={vm.tab}
                  onTab={(t) => {
                    vm.setTab(t);
                    if (t === "logs") void vm.onLoadModuleLogs();
                    if (t === "version_history") void vm.onLoadVersions();
                    if (t === "examples") void vm.onViewExamples();
                  }}
                />
                <SkillWorkspace
                  skill={vm.skill}
                  tab={vm.tab}
                  instructions={vm.instructions}
                  instructionsLoading={vm.instructionsLoading}
                  onLoadInstructions={() => void vm.loadInstructions()}
                  structuredResult={vm.structuredResult}
                  onCopy={() => {
                    const body =
                      vm.structuredResult?.body ??
                      "No example output recorded.";
                    void navigator.clipboard?.writeText(body);
                  }}
                />
              </>
            ) : (
              <div className="lv-sk-detail-empty">
                {vm.loading
                  ? "Loading skill fabric…"
                  : "Select a skill to inspect metadata. Instructions load on demand."}
              </div>
            )}
            {vm.detailLoading ? <div className="lv-sk-detail-loading">Refreshing detail…</div> : null}
          </div>
        </section>
      </main>
    </AppShell>
  );
}
