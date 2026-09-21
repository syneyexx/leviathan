import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA files page matches Bestanden shell and live wiring", async () => {
  const page = await read("components/hades/finalbeta/pages/files-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/files.css");
  const hook = await read("components/hades/features/files/hooks/useHadesFiles.ts");

  assert.match(page, /export function FilesPage\(\{ onNavigate \}/);
  assert.match(page, /FinalBetaShell/);
  assert.match(page, /appClassName="files-app"/);
  assert.match(page, /mainClassName="files-main"/);
  assert.match(page, /Bestanden/);
  assert.match(page, /Beheer, organiseer en deel je bestanden/);
  assert.match(page, /Uploaden/);
  assert.match(page, /Nieuwe map/);
  assert.match(page, /FILES_TABS/);
  assert.match(page, /Mappen/);
  assert.match(page, /Snelle filters/);
  assert.match(page, /Zoeken in bestanden/);
  assert.match(page, /Sorteren: Gewijzigd/);
  assert.match(page, /files-selection-bar/);
  assert.match(page, /SELECTION_ACTIONS/);
  assert.match(page, /Opslagruimte/);
  assert.match(page, /FILES_QUOTE|Data is de brandstof/);
  assert.match(page, /Bestandsvoorbeeld/);
  assert.match(page, /Versie geschiedenis/);
  assert.match(page, /Local AI Platform/);
  assert.match(page, /useHadesFiles/);
  assert.match(page, /data-live="files"/);
  assert.doesNotMatch(page, /mockFileRows/);
  assert.doesNotMatch(page, /FILES_FOLDER_TREE/);
  assert.doesNotMatch(page, /FILES_STORAGE/);
  assert.doesNotMatch(page, /from ["']\.\.\/mocks\/files["']/);
  assert.doesNotMatch(page, /FinalBetaPageRender/);
  assert.doesNotMatch(page, /12\.481/);
  assert.doesNotMatch(page, /142\.6 GB/);
  assert.doesNotMatch(page, /Gesynchroniseerd/);

  assert.match(css, /\.fb-root \.files-page/);
  assert.match(css, /\.fb-root \.files-dual/);
  assert.match(css, /\.fb-root \.files-row\.active/);
  assert.match(css, /\.fb-root \.files-selection-bar/);
  assert.match(css, /\.fb-root \.files-storage-bar/);

  assert.match(hook, /hadesApi\.files/);
  assert.match(hook, /mapIndexedFileToRow/);
  assert.match(hook, /mapWorkspacesToFolderTree/);
  assert.match(hook, /buildQuickFilters/);
  assert.match(hook, /buildStorageSummary/);
  assert.match(hook, /rescanWorkspace|deleteIndexedFile|uploadFile/);
});
