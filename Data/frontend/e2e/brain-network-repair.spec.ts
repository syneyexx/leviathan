import { test, expect, type Page } from '@playwright/test';
import { installBrainV2VisualFixture } from './helpers/brainV2Visual';

async function openBrain(page: Page) {
  await installBrainV2VisualFixture(page);
  await page.route('**/api/events?*', route => route.fulfill({json:{events:[],latest_sequence:0}}));
  await page.goto('/brain');
  await expect(page.locator('.lv-v2-dna-canvas')).toBeVisible();
}
const pixels = (page: Page) => page.locator('canvas.lv-v2-dna-canvas').evaluate((c: HTMLCanvasElement) => c.toDataURL().split('').reduce((h,ch)=>Math.imul(h,31)+ch.charCodeAt(0)|0,0));

for (const width of [1440, 390]) {
  test(`network and tools fit their panel at ${width}px without overlapping following panels`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height:1000});
    await openBrain(page);
    const box = await page.locator('.lv-v2-brain-network-panel').boundingBox();
    const dna = await page.locator('.lv-v2-dna').boundingBox();
    const core = await page.locator('.lv-v2-brain-core').boundingBox();
    const below = await page.locator('.lv-v2-brain-bottom').boundingBox();
    expect(box!.width).toBeLessThanOrEqual(width);
    expect(dna!.y + dna!.height).toBeLessThanOrEqual(box!.y + box!.height);
    expect(below!.y).toBeGreaterThanOrEqual(core!.y + core!.height);
    const canvas = page.locator('.lv-v2-dna-canvas');
    expect(await canvas.evaluate(c => Math.abs(c.width / Math.min(devicePixelRatio,2) - c.getBoundingClientRect().width))).toBeLessThan(1);
    await page.locator('.lv-v2-brain-network-panel').screenshot({path:testInfo.outputPath('network.png')});
    await expect(page.locator('.lv-v2-dna').getByRole('tab',{name:'Bewaren',exact:true})).toBeVisible();
  });
}

test('rotation resumes with an existing selection and camera reset restores the view', async ({page}) => {
  await openBrain(page);
  await page.getByRole('button',{name:'Rotatie pauzeren'}).click();
  // Wait until any initial focus transition and node entrance has settled.
  await page.waitForTimeout(1600);
  const paused = await pixels(page);
  await page.waitForTimeout(180);
  expect(await pixels(page)).toBe(paused);
  await page.getByRole('button',{name:'Rotatie hervatten'}).click();
  await expect.poll(() => pixels(page)).not.toBe(paused);
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.reload();
  await expect(page.locator('.lv-v2-dna-canvas')).toBeVisible();
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(58);
  await page.getByRole('button',{name:'Reset weergave'}).click();
  await page.waitForTimeout(1000);
  const reset = await pixels(page);
  const canvas = page.locator('.lv-v2-dna-canvas');
  await canvas.hover();
  await page.mouse.wheel(0,-400);
  await expect.poll(() => pixels(page)).not.toBe(reset);
  await page.getByRole('button',{name:'Reset weergave'}).click();
  await expect.poll(() => pixels(page)).toBe(reset);
});

test('retrieval activation uses API identities and reports nodes outside the loaded graph', async ({page}) => {
  await installBrainV2VisualFixture(page);
  await page.route('**/api/events?*', route => route.fulfill({json:{events:[{
    sequence:1,event_id:'activation-1',created_at_ms:Date.now(),category:'brain',name:'knowledge_activation',level:'INFO',message:'brain.knowledge_activation',
    payload:{request_id:'request-1',phase:'complete',node_ids:['concept:bitcoin','knowledge:document:outside'],identifiers_available:true,hit_count:2},
  }],latest_sequence:1}}));
  await page.goto('/brain');
  await expect(page.getByText('Kennis geactiveerd',{exact:true})).toBeVisible();
  await expect(page.getByText(/1 van 2 opgehaalde kennisnodes zichtbaar/)).toBeVisible();
});

test('bounded 250-node API graph supports relation mode and exposes every node to keyboard users', async ({page}, testInfo) => {
  await installBrainV2VisualFixture(page);
  await page.addInitScript(() => { (window as Window & {__LV_V2_VISUAL_FIXTURE__?:boolean}).__LV_V2_VISUAL_FIXTURE__ = false; });
  const nodes = Array.from({length:250},(_,i)=>({id:`knowledge:document:doc-${i}`,type:'knowledge.document',label:`Document ${i}`,meta:{}}));
  const edges = nodes.slice(1).map((n,i)=>({id:`edge-${i}`,source:nodes[0].id,target:n.id,relation:'related'}));
  await page.route('**/api/brain/catalog?*', route => route.fulfill({json:{nodes,edges,page:{complete:true,next_source:12,next_offset:0},stats:{node_count:250,edge_count:249,by_type:{'knowledge.document':250},by_relation:{related:249}},truth:{bounded_projection:true}}}));
  await page.route('**/api/events?*', route => route.fulfill({json:{events:[],latest_sequence:0}}));
  await page.goto('/brain');
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(250);
  await page.locator('.lv-v2-dna').getByRole('button',{name:'Relaties',exact:true}).click();
  await expect(page.locator('.lv-v2-dna').getByRole('button',{name:'Relaties',exact:true})).toHaveClass(/is-active/);
  await page.waitForTimeout(800);
  await page.locator('.lv-v2-dna__stage').screenshot({path:testInfo.outputPath('dense-relations.png')});
  const last = page.locator('.lv-v2-dna-a11y-list button').last();
  await last.focus();
  await last.press('Enter');
  await expect(page.locator('.lv-v2-brain-selected__identity h4')).toHaveText('Document 249');
});

test('relation lines default off and can be toggled without removing graph data', async ({page}, testInfo) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await openBrain(page);
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(58);
  await page.getByRole('button',{name:'Reset weergave'}).click();
  const toggle = page.getByRole('button',{name:'Relatielijnen tonen',exact:true});
  await expect(toggle).toHaveAttribute('aria-pressed','false');
  await page.waitForTimeout(500);
  const clean = await pixels(page);
  await page.locator('.lv-v2-dna__stage').screenshot({path:testInfo.outputPath('dna-reference.png')});
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed','true');
  await expect.poll(() => pixels(page)).not.toBe(clean);
  await toggle.click();
  await expect.poll(() => pixels(page)).toBe(clean);
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(58);
  await page.getByRole('button',{name:'Relaties',exact:true}).click();
  await expect(toggle).toHaveAttribute('aria-pressed','false');
  await toggle.press('Space');
  await expect(toggle).toHaveAttribute('aria-pressed','true');
});

test('reduced-motion users can explicitly start and pause rotation', async ({page}) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await openBrain(page);
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(58);
  const play = page.getByRole('button',{name:'Rotatie hervatten'});
  await expect(play).toBeEnabled();
  const stopped = await pixels(page);
  await page.waitForTimeout(200);
  expect(await pixels(page)).toBe(stopped);
  await play.click();
  await expect(page.getByText("Rotatie actief", {exact:true})).toBeVisible();
  await expect.poll(()=>pixels(page)).not.toBe(stopped);
  await page.getByRole('button',{name:'Rotatie pauzeren'}).click();
  await page.waitForTimeout(100);
  const paused = await pixels(page);
  await page.waitForTimeout(200);
  expect(await pixels(page)).toBe(paused);
});

test('pages beyond 250 load and new data adds navigable DNA segments', async ({page}) => {
  await installBrainV2VisualFixture(page);
  let count = 301;
  const requested: number[] = [];
  await page.route('**/api/brain/catalog?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    requested.push(offset);
    const nodes = Array.from({length:Math.min(50,Math.max(0,count-offset))},(_,i)=>({id:`knowledge:document:doc-${offset+i}`,type:'knowledge.document',label:`Live document ${offset+i}`,meta:{}}));
    return route.fulfill({json:{nodes,edges:[],page:{complete:offset+50>=count,next_source:0,next_offset:offset+50}}});
  });
  await page.goto('/brain');
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(301);
  expect(requested).toContain(300);
  const slider = page.getByRole('slider',{name:'DNA segment',exact:true});
  await expect(slider).toHaveAttribute('max','6');
  await slider.fill('6');
  await expect(page.getByText('301–301 van 301 nodes · maximaal 60 per segment',{exact:true})).toBeVisible();
  const last = page.locator('.lv-v2-dna-a11y-list button').last();
  await last.focus(); await last.press('Enter');
  await expect(page.locator('.lv-v2-brain-selected__identity h4')).toHaveText('Live document 300');
  count = 361;
  await page.getByRole('button',{name:'Refresh dashboard',exact:true}).click();
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(361);
  await expect(slider).toHaveAttribute('max','7');
  await page.getByRole('textbox',{name:'Zoek nodes',exact:true}).fill('Live document 360');
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toHaveCount(1);
  await expect(page.locator('.lv-v2-dna-a11y-list button')).toContainText('Live document 360');
});
