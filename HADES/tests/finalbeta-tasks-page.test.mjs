import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA tasks page matches Taken Kanban reference layout", async () => {
  const page = await read("components/hades/finalbeta/pages/tasks-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/tasks.css");
  const index = await read("components/hades/styles/finalbeta/index.css");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");

  assert.match(page, /useHadesTasks/);
  assert.match(page, /data-live="tasks"/);
  assert.doesNotMatch(page, /mockKanbanTasks/);
  assert.match(page, /tasks-page/);
  assert.match(page, /Execution turns intelligence into reality/);
  assert.match(page, /Kanban/);
  assert.match(page, /Snelle acties/);
  assert.match(page, /Taakstatistieken/);
  assert.match(page, /Taak details/);
  assert.match(css, /\.fb-root \.tasks-page/);
  assert.match(css, /\.fb-root \.tasks-board/);
  assert.match(css, /\.fb-root \.tasks-card\.active/);
  assert.match(index, /@import "\.\/v2\/tasks\.css"/);
  assert.match(app, /page === "tasks"/);
});

test("FINALBETA Taken submenu tabs Lijst through Tijdlijn are wired", async () => {
  const page = await read("components/hades/finalbeta/pages/tasks-page.tsx");
  const index = await read("components/hades/finalbeta/pages/tasks/index.ts");
  const lijst = await read("components/hades/finalbeta/pages/tasks/tab-lijst.tsx");
  const mijn = await read("components/hades/finalbeta/pages/tasks/tab-mijn-taken.tsx");
  const kalender = await read("components/hades/finalbeta/pages/tasks/tab-kalender.tsx");
  const tijdlijn = await read("components/hades/finalbeta/pages/tasks/tab-tijdlijn.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/tasks.css");
  const mocks = await read("components/hades/finalbeta/mocks/tasks.ts");

  for (const tab of ["Kanban", "Lijst", "Mijn taken", "Kalender", "Tijdlijn", "Analytics"]) {
    assert.match(page, new RegExp(tab.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }

  assert.match(page, /TasksTabLijst/);
  assert.match(page, /TasksTabMijnTaken/);
  assert.match(page, /TasksTabKalender/);
  assert.match(page, /TasksTabTijdlijn/);
  assert.match(page, /Small steps compound into extraordinary results/);
  assert.match(page, /Focus op wat voor jou belangrijk is/);
  assert.match(page, /Analytics volgt in een volgende iteratie/);

  assert.match(index, /tab-lijst/);
  assert.match(index, /tab-mijn-taken/);
  assert.match(index, /tab-kalender/);
  assert.match(index, /tab-tijdlijn/);

  assert.match(lijst, /tasks-lijst-tab/);
  assert.match(lijst, /tasks-status-filters/);
  assert.match(lijst, /tasks-table/);
  assert.match(lijst, /Taaknaam/);
  assert.match(lijst, /Voortgang/);

  assert.match(mijn, /tasks-mine-tab/);
  assert.match(mijn, /Taken vandaag/);
  assert.match(mijn, /Voltooiingsgraad/);
  assert.match(mijn, /Deze week/);
  assert.match(mijn, /Geschatte tijd/);

  assert.match(kalender, /tasks-kalender-tab/);
  assert.match(kalender, /tasks-cal-grid/);
  assert.match(kalender, /Vandaag/);
  assert.match(kalender, /September 2026/);
  assert.match(kalender, /today/);

  assert.match(tijdlijn, /tasks-tijdlijn-tab/);
  assert.match(tijdlijn, /tasks-gantt/);
  assert.match(tijdlijn, /FinalBetaKanbanTask/);
  assert.match(tijdlijn, /data-live="tasks-tijdlijn"/);
  assert.doesNotMatch(tijdlijn, /mockTimelineGroups/);
  assert.match(tijdlijn, /tasks-gantt-legend/);
  assert.match(page, /TasksTabTijdlijn tasks=\{kanbanTasks\}/);

  assert.match(css, /\.fb-root \.tasks-lijst-tab/);
  assert.match(css, /\.fb-root \.tasks-mine-tab/);
  assert.match(css, /\.fb-root \.tasks-kalender-tab/);
  assert.match(css, /\.fb-root \.tasks-tijdlijn-tab/);
  assert.match(css, /\.fb-root \.tasks-gantt/);
  assert.match(css, /\.fb-root \.tasks-cal-cell\.today/);
  assert.match(css, /\.fb-root \.tasks-table tbody tr\.active/);
  assert.match(css, /\.fb-root \.tasks-mine-chip\.active/);

  assert.match(mocks, /LIST_STATUS_FILTERS/);
  assert.match(mocks, /MY_TASK_CHIPS/);
  assert.match(mocks, /TIMELINE_TOTAL_DAYS/);
  assert.match(mocks, /projectTone/);
});
