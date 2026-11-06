/* Hands the Forge logic modules to the classic-script JSX files.
 *
 * itemset.js, patchstrip.js, loadout.js and build-overlay.js stay ES modules (they hold
 * the save-body builders and the overlay, and are imported by each other). JSX files are
 * classic scripts, so they cannot import. This module imports the four, publishes every
 * export on window.ForgeLib, and fires `forgelib:ready`. Load it as type="module" ahead
 * of the JSX: module scripts run in document order with deferred ones, so ForgeLib is
 * there before the first JSX body runs; the event covers any late reader.
 */
import * as itemset from './itemset.js';
import * as patchstrip from './patchstrip.js';
import * as loadout from './loadout.js';
import * as overlay from './build-overlay.js';

// export names are disjoint across the four files, so one flat object is safe
window.ForgeLib = Object.assign({}, itemset, patchstrip, loadout, overlay);
window.dispatchEvent(new Event('forgelib:ready'));
