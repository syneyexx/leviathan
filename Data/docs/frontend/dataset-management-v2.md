# Dataset Management V2

## Route & ownership

- Path: `/dataset-management`
- Menu: **LLM → Dataset Manager** (MAIN_MENU / `v2ChildrenFromMainMenu("llm")`)
- Separate surface: `/datasets` under Onderzoek & Kennis — same Dataset domain, different product job

## Composition

- `DatasetManagementPage` + `useDatasetManagementWorkspace`
- `src/components/dataset-management/*`
- Shared: `DatasetActivityConsole`, `useDatasetActivity`
- Shell: `AppShell variant="v2"`
- Styles: global `leviathan-v2.css` under `.lv-v2-page--dataset-management` (no page-local CSS file)

## APIs

| Concern | Endpoint |
|---|---|
| Library page | `GET /api/datasets?q&limit&offset&status&source&category&split&tag&type&sort` |
| KPIs / storage / tags | `GET /api/datasets/overview` |
| Detail | `GET /api/datasets/{id}` |
| Semantic save | `PATCH /api/datasets/{id}/semantic` |
| Jobs | `GET/POST /api/datasets/jobs…` |
| Brain learn | `POST /api/datasets/{id}/learn` |

## Truth rules

- Totals come from overview / SQL `COUNT`, never `datasets.length`
- Null `rowCount` → partial/UNMEASURED samples, not zero
- Quality unknown until validation evidence exists
- Catalog Status ≠ page Online/Offline
- Local dataset ≠ Geleerd in Brain
- Training consumes immutable `datasetVersionId`

## Visual regression

- Reference: `Data/docs/ui_reference/dataset-management-llm-v2-reference.jpg` (1672×941)
- Fixture: `src/mocks/datasetManagementV2VisualFixture.ts` (Playwright only)
- Spec: `e2e/dataset-management-v2.visual.spec.ts`
