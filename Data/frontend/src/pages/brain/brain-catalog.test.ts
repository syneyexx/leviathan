import {describe,it,expect} from 'vitest';
import {loadBrainCatalog, type BrainCatalogPage} from './brain-catalog';

describe('complete Brain catalog traversal', () => {
  it('loads beyond 250/500, joins cross-page edges and keeps authoritative metadata', async () => {
    const all = Array.from({length:603},(_,i)=>({id:`doc:${i}`,type:'knowledge.document',label:`Document ${i}`,meta:{catalog_reference:false}}));
    const graph = await loadBrainCatalog(async ({offset}) => ({
      nodes: [...all.slice(offset,offset+50), {id:'doc:0',type:'knowledge.document',label:'0',meta:{catalog_reference:true}}],
      edges: offset===0 ? [{id:'cross',source:'doc:0',target:'doc:602',relation:'SUPPORTS'}] : [],
      page:{complete:offset+50>=all.length,next_source:0,next_offset:offset+50},
    }),new AbortController().signal);
    expect(graph.nodes).toHaveLength(603);
    expect(graph.nodes.find(n=>n.id==='doc:0')?.label).toBe('Document 0');
    expect(graph.edges[0].target).toBe('doc:602');
  });
  it('rejects an incomplete or broken cursor instead of claiming completion', async () => {
    await expect(loadBrainCatalog(async()=>({nodes:[],edges:[],page:{complete:false,next_source:0,next_offset:0}}),new AbortController().signal)).rejects.toThrow(/vervolgpagina/);
    await expect(loadBrainCatalog(async()=>({} as BrainCatalogPage),new AbortController().signal)).rejects.toThrow(/backend/);
  });
  it('honors cancellation between pages', async () => {
    const controller = new AbortController();
    let count = 0;
    await expect(loadBrainCatalog(async()=>{
      count++;controller.abort();
      return {nodes:[],edges:[],page:{complete:false,next_source:1,next_offset:0}};
    },controller.signal)).rejects.toThrow();
    expect(count).toBe(1);
  });
});
