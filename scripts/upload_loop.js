/**
 * Blanxer bulk product uploader — paste this into the Blanxer dashboard tab
 * via mcp__Claude_in_Chrome__javascript_tool.
 *
 * Usage:
 *   1. Replace the placeholders below (PRODUCTS, STORE_ID, OUTLET_ID, CHANNEL, DELAY_MS).
 *   2. Execute. The script kicks off a background async job and returns immediately.
 *   3. Poll progress with a follow-up exec:
 *        JSON.stringify({
 *          done:  window.__blanxer_upload.done,
 *          count: window.__blanxer_upload.log.length,
 *          total: window.__blanxer_upload.total,
 *          errs:  window.__blanxer_upload.log.filter(e => e.error).length,
 *          last3: window.__blanxer_upload.log.slice(-3).map(
 *            e => ({i: e.idx, name: e.name, ok: e.ok, err: e.error})
 *          )
 *        })
 *
 * Channel codes: 1 = All, 2 = Website, 3 = POS.
 * Each product row needs: { name, qty, costRate, sellingRate }, and may carry
 * an optional { tags: ['coming_soon', 'seller:acme'] }. TAGS below is merged
 * onto every row's own tags. Tags can only be set here at create time — to
 * retag products that already exist, use scripts/manage_tags.py.
 */

(() => {
  // ---- FILL THESE IN ----
  const PRODUCTS = [
    // { name: '1-CordSet-10May', qty: 28, costRate: 1100, sellingRate: 1850 },
  ];
  const STORE_ID  = ''; // e.g. localStorage.getItem('current_store_id')
  const OUTLET_ID = ''; // looked up from /inventory/outlets/{store_id}
  const CHANNEL   = 3;  // POS
  const DELAY_MS  = 3000;
  const TAGS      = []; // applied to every product, e.g. ['seller:acme']
  // -----------------------

  if (!PRODUCTS.length || !STORE_ID || !OUTLET_ID) {
    return 'ERROR: PRODUCTS, STORE_ID, and OUTLET_ID must be set before running.';
  }

  const token = localStorage.getItem('blanxer_access_token');
  if (!token) return 'ERROR: no blanxer_access_token in localStorage — log in first.';

  const headers = {
    'Authorization': 'Bearer ' + token,
    'Content-Type': 'application/json'
  };

  window.__blanxer_upload = {
    log: [],
    total: PRODUCTS.length,
    done: false,
    started: Date.now()
  };
  const state = window.__blanxer_upload;

  const buildCreateBody = (p) => ({
    name: p.name,
    slug: '', brand: '', categories: [],
    description: '', long_description: '',
    images: [], image_urls: [],
    channel: CHANNEL,
    showVariant: false, showColorPreview: false, continue_selling: true,
    price: p.sellingRate,
    compare_at_price: 0,
    cost_per_item: 0,
    weight: 0,
    quantity: 0,
    sku: '',
    color_name: '', color_codes: [], size_name: '',
    colors: [], sizes: [],
    variants: [], custom_fields: [], tags: [...new Set([...TAGS, ...(p.tags || [])])],
    releaseDate: null, similar_products: []
  });

  const buildStockBody = (productId, p) => ({
    store_id: STORE_ID,
    outlet_id: OUTLET_ID,
    reference_number: '',
    items: [{
      product_id: productId,
      variant_id: '',
      quantity: p.qty,
      cost_price: p.costRate,
      bin_location: ''
    }]
  });

  (async () => {
    for (let i = 0; i < PRODUCTS.length; i++) {
      const p = PRODUCTS[i];
      const entry = {
        idx: i + 1,
        name: p.name,
        qty: p.qty,
        cost: p.costRate,
        sell: p.sellingRate,
        ts: Date.now()
      };
      try {
        // 1. Create product
        const cr = await fetch('https://api.blanxer.com/product/' + STORE_ID, {
          method: 'POST', headers, body: JSON.stringify(buildCreateBody(p))
        });
        const cj = await cr.json();
        if (!cj.success || !cj.product || !cj.product._id) {
          entry.error = 'create-failed status=' + cr.status +
                        ' resp=' + JSON.stringify(cj).slice(0, 200);
          state.log.push(entry);
          if (i < PRODUCTS.length - 1) await new Promise(r => setTimeout(r, DELAY_MS));
          continue;
        }
        entry.productId = cj.product._id;

        // 2. Stock in
        const sr = await fetch('https://api.blanxer.com/inventory/stock-in', {
          method: 'POST', headers,
          body: JSON.stringify(buildStockBody(cj.product._id, p))
        });
        const sj = await sr.json();
        entry.stock = sj;
        entry.ok = sr.ok;
        if (!sr.ok) entry.error = 'stock-in-failed status=' + sr.status;
      } catch (e) {
        entry.error = String(e);
      }
      state.log.push(entry);
      if (i < PRODUCTS.length - 1) await new Promise(r => setTimeout(r, DELAY_MS));
    }
    state.done = true;
    state.elapsed_sec = Math.round((Date.now() - state.started) / 1000);
  })();

  return 'started job for ' + PRODUCTS.length + ' products, delay=' + DELAY_MS + 'ms';
})();
