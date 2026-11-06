/* The Hub's one basemap, for every Leaflet map on it.
   Consumers: trips.js (the liftoff ride map and the day map) and food-view.js.

   This replaces `L.tileLayer(openstreetmap)` + a CSS filter over the tile pane.
   That pairing had a ceiling no amount of grading got past. OSM's standard raster
   is a tourist map: highway shields, truck-route labels, ferry dashes and every
   side street, all drawn at the same weight in tan and green. A filter can change
   the colour of that information but it cannot remove it, so the map stayed busy
   whatever the numbers said — and the dark surface had the extra problem that
   inverting an orange motorway lands it on salmon, which then reads as the loudest
   thing on a card whose whole subject is a blue route.

   Esri's Canvas layers are drawn for this job instead: a near-neutral ground with
   no shields and no clutter, published in a light and a dark cut, so each surface
   gets real tiles rather than an inversion of the other one's. Keyless, unlike
   CARTO's basemaps, which now answer 200 with a tile that reads API KEY REQUIRED
   across it — a status code is not a picture, and that one only showed up on screen.

   Base and labels are two services. Keeping them apart is what lets the labels sit
   ABOVE the ground and BELOW the route: its own pane at z-index 250, between the
   tiles at 200 and the overlays at 400. */
(() => {
  var CANVAS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_";

  function url(surface, layer) {
    return CANVAS + (surface === "dark" ? "Dark" : "Light") + "_Gray_" + layer
      + "/MapServer/tile/{z}/{y}/{x}";
  }

  function surface() {
    return document.documentElement.getAttribute("data-surface") === "dark" ? "dark" : "light";
  }

  /* Adds the ground to `map` and keeps it on the current surface for as long as the
     map lives. Returns nothing — nothing downstream has ever needed the layer back. */
  window.hubBasemap = (map) => {
    // The labels pane. pointer-events off or the label raster eats clicks meant for
    // the marks underneath it, which are the only clickable thing on any of these maps.
    map.createPane("labels");
    map.getPane("labels").style.zIndex = 250;
    map.getPane("labels").style.pointerEvents = "none";

    /* Two rules in one object, and they interact — read them together.

       maxNativeZoom is the fix for "no map data". Esri's Canvas services are only
       published to level 16. Past it they do not 404 — they answer 200 with a
       2521-byte raster that has NO MAP DATA AVAILABLE printed across it, so a reader
       who kept pinching in got a wall of grey text instead of their route (verified
       2026-08-31: z14/15/16 come back 14-20KB of real ground, z17/18/19 come back the
       same 2521 bytes every time). Capping the REQUEST while leaving the map's own
       maxZoom at 19 makes Leaflet stretch the deepest real tile instead of asking for
       one that does not exist: softer ground close in, which is the honest look for a
       basemap that has no more detail, rather than a placeholder claiming there is no
       map at all.

       Drawn at twice the resolution the box asks for, on every screen.

       Each 256px tile is painted into a 128px square one zoom level deeper, which
       is four tiles where there was one and twice the detail per pixel. This is
       exactly what Leaflet's own `detectRetina` does, done unconditionally instead
       of only when devicePixelRatio > 1 — the ride map is FROZEN, so its tiles are
       rasterised once and then read for as long as the card is open, and a 1x
       screen still gets a visibly cleaner downsample of a sharp raster than an
       upsample of a soft one. Station names in the label layer are the thing that
       actually gains; they were the softest text on the card.

       This is why maxNativeZoom reads 15 and not the 16 the services publish to.
       Leaflet adds zoomOffset to the tile key AFTER the native-zoom clamp, so a 16
       here would ask Esri for level 17 and bring the NO MAP DATA raster straight
       back. 15 + 1 lands on 16, which is the deepest level that exists. */
    var at = surface();
    var HD = { tileSize: 128, zoomOffset: 1, maxZoom: 19, maxNativeZoom: 15 };
    var BASE = Object.assign({
                 attribution: "Esri, HERE, Garmin, OpenStreetMap contributors" }, HD);
    var LABEL = Object.assign({ pane: "labels" }, HD);
    var base = L.tileLayer(url(at, "Base"), BASE).addTo(map);
    var labels = L.tileLayer(url(at, "Reference"), LABEL).addTo(map);

    /* The surface toggles at runtime, so the ground has to follow it.

       This swaps LAYERS, not URLs, and setUrl() is the reason. The liftoff ride map
       runs `zoomSnap: 0`, so it sits at fractional zooms like 12.58. setUrl redraws
       without going back through Leaflet's _setView, which is the only place the zoom
       is ROUNDED for the tile key — so every request went out as
       .../tile/12.582788483371552/2306/1807, Esri 404'd all of them, and the card
       rendered a route floating on empty grey. Adding a layer re-runs _setView and
       gets an integer. Nothing in the numbers said this; the blank map on screen did.

       New ground goes on before the old comes off, so the swap never shows a hole.
       The drop is idempotent — removeLayer on an absent layer is a no-op — so the
       timer is just the backstop for a `load` that never arrives on a dead network. */
    function swap() {
      var now = surface();
      if (now === at) return;
      at = now;
      var old = [base, labels];
      function drop() { old.forEach((l) => { map.removeLayer(l); }); }
      base = L.tileLayer(url(at, "Base"), BASE).addTo(map);
      labels = L.tileLayer(url(at, "Reference"), LABEL).addTo(map);
      base.once("load", drop);
      setTimeout(drop, 3000);
    }

    /* Observing <html> is the same signal theme-switch.js paints its own glyph from.
       Dropped with the map: every one of these maps is destroyed and rebuilt on a tab
       or day change, and the observers would otherwise pile up one per render. */
    var obs = new MutationObserver(swap);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-surface"] });
    map.on("unload", () => { obs.disconnect(); });
  };
})();
