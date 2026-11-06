/* The Hub's one basemap, as a component. React port of basemap.js; the plain file stays
   until its last consumer (trips.js) converts.

   <HubUI.Basemap map={leafletMap} /> renders nothing: it adds the Esri Canvas ground
   (base + labels, twice the resolution the box asks for) to the map and keeps it on the
   current light/dark surface for as long as the map lives. Every reason the tile options
   look the way they do is in basemap.js: maxNativeZoom 15 + zoomOffset 1 lands on level
   16, the deepest the services publish, and a surface flip swaps LAYERS, never setUrl(). */
window.HubUI = window.HubUI || {};
(() => {
  const { useEffect } = React;
  const CANVAS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_";

  function url(surface, layer) {
    return CANVAS + (surface === "dark" ? "Dark" : "Light") + "_Gray_" + layer
      + "/MapServer/tile/{z}/{y}/{x}";
  }

  function surface() {
    return document.documentElement.getAttribute("data-surface") === "dark" ? "dark" : "light";
  }

  const HD = { tileSize: 128, zoomOffset: 1, maxZoom: 19, maxNativeZoom: 15 };
  const BASE = Object.assign({ attribution: "Esri, HERE, Garmin, OpenStreetMap contributors" }, HD);
  const LABEL = Object.assign({ pane: "labels" }, HD);

  function attach(map) {
    // The labels pane. pointer-events off or the label raster eats clicks meant for
    // the marks underneath it, which are the only clickable thing on any of these maps.
    map.createPane("labels");
    map.getPane("labels").style.zIndex = 250;
    map.getPane("labels").style.pointerEvents = "none";

    let at = surface();
    let base = L.tileLayer(url(at, "Base"), BASE).addTo(map);
    let labels = L.tileLayer(url(at, "Reference"), LABEL).addTo(map);

    // New ground goes on before the old comes off, so the swap never shows a hole.
    // The drop is idempotent, so the timer is just the backstop for a `load` that
    // never arrives on a dead network.
    function swap() {
      const now = surface();
      if (now === at) return;
      at = now;
      const old = [base, labels];
      const drop = () => { old.forEach((l) => { map.removeLayer(l); }); };
      base = L.tileLayer(url(at, "Base"), BASE).addTo(map);
      labels = L.tileLayer(url(at, "Reference"), LABEL).addTo(map);
      base.once("load", drop);
      setTimeout(drop, 3000);
    }

    const obs = new MutationObserver(swap);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-surface"] });
    map.on("unload", () => { obs.disconnect(); });
    return () => obs.disconnect();
  }

  HubUI.Basemap = function Basemap({ map }) {
    useEffect(() => (map ? attach(map) : undefined), [map]);
    return null;
  };
})();
