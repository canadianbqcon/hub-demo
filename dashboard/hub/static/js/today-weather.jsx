/* Home today-briefing · 1 of 4: NYC weather: the WMO code table, the forecast URL, and the useNycWeather hook.

   Split from today.jsx 2026-07-29 (1065 lines), which was itself split out of
   chrome.jsx the same day. index.html loads the four in this order and each is
   its own Babel script with its own scope, so every name another file needs is
   handed over explicitly through the Object.assign at the bottom, the same
   pattern chrome.jsx uses. React hooks are re-destructured per file for the
   same reason.
*/

/* Home today-briefing subsystem: NYC weather, the day-view calendar column, and
   the today zone (header + the three column caps). Split out of chrome.jsx on
   2026-07-29. It was ~940 of that file's 1575 lines, and only App.jsx (home)
   consumes any of it, while purchases.html and work.html load chrome.jsx and
   used none of it.

   Loads AFTER chrome.jsx: nothing here is referenced by chrome, but this file
   has no dependency on chrome either (WMO_LABEL/WX_URL/useNycWeather came along
   because they are home-only too). Everything is a browser global via the
   Object.assign at the bottom, same pattern as chrome.jsx.
*/

const { useState, useEffect } = React;

/* ---------------- WeatherStat ----------------
   live NYC weather for the status strip. Open-Meteo current endpoint (free, no
   API key, CORS-enabled), refreshed every 15 min. Text-only temp + a short
   lowercase condition to match the strip's monochrome hub restraint (no
   color emoji). Falls back to a dash on first paint / fetch failure so the
   strip never breaks. WMO weather-code -> label map below. */
const WMO_LABEL = {
  0: "clear",
  1: "mostly clear", 2: "partly cloudy", 3: "overcast",
  45: "fog", 48: "rime fog",
  51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
  56: "freezing drizzle", 57: "freezing drizzle",
  61: "light rain", 63: "rain", 65: "heavy rain",
  66: "freezing rain", 67: "freezing rain",
  71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
  80: "light showers", 81: "showers", 82: "heavy showers",
  85: "snow showers", 86: "snow showers",
  95: "thunderstorm", 96: "thunderstorm", 99: "hail thunderstorm",
};
const WX_URL =
  "https://api.open-meteo.com/v1/forecast?latitude=40.7128&longitude=-74.006" +
  "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m" +
  "&hourly=temperature_2m,precipitation_probability,weather_code,precipitation,snowfall,relative_humidity_2m" +
  "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max," +
  "apparent_temperature_max,wind_speed_10m_max,uv_index_max,sunrise,sunset,precipitation_sum,snowfall_sum" +
  "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch" +
  "&timezone=America%2FNew_York&forecast_days=8";

/* shared NYC weather. Fetched once and passed down to the footer strip and the
   day-navigable briefing so we hit Open-Meteo a single time per load (refreshes
   every 15 min). Returns null until the first response lands, then an object:
     { today: <entry>, byDate: { "YYYY-MM-DD": <entry> } }
   where each entry is { temp, code, hi, lo, precip, feels, wind, uv, sunrise,
   sunset, hours: [{ iso, hour, temp, code, precip }] }. byDate covers today
   through +7 (the forecast horizon); past days have no entry, so the briefing
   simply omits weather there. The today entry overlays live current conditions
   (temp, code, feels, wind) onto today's daily hi/lo/precip. Only the base five
   fields survive into a past day (briefing_snapshot persists those); the extras
   are live-only and their rows self-hide when absent. */
// Air quality (Open-Meteo, CORS-open, Brooklyn pin) and pollen (pollen.com via the
// Hub's own relay: it refuses browser cross-site calls). Both change slowly, so
// once per load is enough; each fails independently to null and its reading
// self-hides.
const AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=40.69&longitude=-73.99&current=us_aqi,pm2_5";
function useNycWeather() {
  const [wx, setWx] = useState(null);
  const [extras, setExtras] = useState({});
  useEffect(() => {
    let cancelled = false;
    fetch(AQ_URL).then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (!cancelled && d && d.current) setExtras((e) => ({ ...e, aqi: d.current.us_aqi, pm25: d.current.pm2_5 }));
    }).catch(() => {});
    fetch("/api/wx-extras").then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (!cancelled && d && d.pollen && d.pollen.index != null) setExtras((e) => ({ ...e, pollen: d.pollen }));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(WX_URL)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (cancelled || !d || !d.daily) return;
          const dl = d.daily;
          const times = dl.time || [];
          const r = (v) => (v != null ? Math.round(v) : null);
          const byDate = {};
          for (let i = 0; i < times.length; i++) {
            const hi = r(dl.temperature_2m_max?.[i]);
            const lo = r(dl.temperature_2m_min?.[i]);
            byDate[times[i]] = {
              // headline temp on a forecast day is the day's high; today's is
              // overwritten with the live current temp just below.
              temp: hi,
              code: dl.weather_code?.[i],
              hi,
              lo,
              precip: dl.precipitation_probability_max?.[i] ?? null,
              // a forecast day's "feels like" is its apparent high (paired with
              // temp = the actual high); today's is replaced by the live value.
              feels: r(dl.apparent_temperature_max?.[i]),
              wind: r(dl.wind_speed_10m_max?.[i]),
              uv: r(dl.uv_index_max?.[i]),
              sunrise: dl.sunrise?.[i] ?? null,
              sunset: dl.sunset?.[i] ?? null,
              rainTotal: dl.precipitation_sum?.[i] ?? null,   // inches, liquid
              snowTotal: dl.snowfall_sum?.[i] ?? null,        // inches
            };
          }
          // Hourly series kept FLAT and ascending, not bucketed per day —
          // consumers slice out the day they want (see dayRail).
          // Timestamps are already local ("YYYY-MM-DDTHH:MM") because the request
          // pins the timezone, so string compares order correctly and the date
          // half is the local day key — no conversion anywhere.
          const hl = d.hourly || {};
          const hours = (hl.time || []).map((iso, i) => ({
            iso,
            hour: parseInt(iso.slice(11, 13), 10),
            temp: r(hl.temperature_2m?.[i]),
            code: hl.weather_code?.[i],
            precip: hl.precipitation_probability?.[i] ?? null,
            inches: hl.precipitation?.[i] ?? 0,
            snow: hl.snowfall?.[i] ?? 0,
            hum: hl.relative_humidity_2m?.[i] ?? null,
          }));
          const todayIso = times[0];
          if (todayIso && d.current) {
            byDate[todayIso] = {
              ...byDate[todayIso],
              temp: Math.round(d.current.temperature_2m),
              code: d.current.weather_code,
              feels: r(d.current.apparent_temperature),
              wind: r(d.current.wind_speed_10m),
              hum: d.current.relative_humidity_2m ?? null,
            };
          }
          setWx({ today: todayIso ? byDate[todayIso] : null, byDate, hours });
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 15 * 60 * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);
  return React.useMemo(() => (wx ? { ...wx, ...extras } : null), [wx, extras]);
}

/* ---------------- TodayBriefing ----------------
   Home morning-prep content for the AlwaysSeeTab. Aggregates across all of
   today's events. Every /api/home access is null-guarded (progressive load). */
// Events for a specific day key ("YYYY-MM-DD"); [] when that day isn't in the
// window. Drives the day-navigable briefing.

/* One glyph per weather family (clear, cloudy, fog, wet, frozen, violent), the art
   the trips weather tab draws. ponytail: copied from trips-context.jsx WX_ART,
   which lives in that module's closure; lift both into one shared file if a third
   page wants them. `night` swaps the clear-sky glyphs for their moon. */
const WX_ART = {
  sun:   `<circle cx="12" cy="12" r="4.4"/><path d="M12 3.2V5.4M12 18.6V20.8M3.2 12H5.4M18.6 12H20.8M5.8 5.8 7.4 7.4M16.6 16.6 18.2 18.2M18.2 5.8 16.6 7.4M7.4 16.6 5.8 18.2"/>`,
  part:  `<circle cx="9" cy="8.6" r="3.3"/><path d="M9 2.6V4.2M3 8.6H4.6M4.9 4.5 6 5.6M13.1 4.5 12 5.6"/><path d="M8.6 20.4A3.5 3.5 0 0 1 8.6 13.4A5.3 5.3 0 0 1 18.6 14.9A3 3 0 0 1 18.6 20.4Z"/>`,
  cloud: `<path d="M7.4 19.6A4 4 0 0 1 7.9 11.7A6 6 0 0 1 19.2 13.4A3.2 3.2 0 0 1 18.6 19.6Z"/>`,
  fog:   `<path d="M7.6 13.4A3.4 3.4 0 0 1 8.1 6.4A5.4 5.4 0 0 1 18.4 7.9A2.9 2.9 0 0 1 17.9 13.4Z"/><path d="M4.4 16.8H19.6M6.8 20H17.2"/>`,
  rain:  `<path d="M7.6 14.4A3.6 3.6 0 0 1 8.1 7.1A5.6 5.6 0 0 1 18.7 8.6A3 3 0 0 1 18.2 14.4Z"/><path d="M8.8 17.2 7.6 20.6M13 17.2 11.8 20.6M17.2 17.2 16 20.6"/>`,
  snow:  `<path d="M7.6 13.6A3.6 3.6 0 0 1 8.1 6.3A5.6 5.6 0 0 1 18.7 7.8A3 3 0 0 1 18.2 13.6Z"/><path d="M8.6 17.2v2.6M7.4 18.5h2.4M15.4 17.2v2.6M14.2 18.5h2.4M12 19.4v2.4M10.9 20.6h2.2"/>`,
  storm: `<path d="M7.6 13.6A3.6 3.6 0 0 1 8.1 6.3A5.6 5.6 0 0 1 18.7 7.8A3 3 0 0 1 18.2 13.6Z"/><path d="M13.4 15.4 10 19.2h3.2L11.4 22.4"/>`,
  moon:  `<path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8A8.6 8.6 0 1 0 20.2 14.6Z"/>`,
  pmoon: `<path d="M14.6 9.6A5.2 5.2 0 0 1 8.2 3.2A5.2 5.2 0 1 0 14.6 9.6Z"/><path d="M8.4 20.4A3.5 3.5 0 0 1 8.4 13.4A5.3 5.3 0 0 1 18.4 14.9A3 3 0 0 1 18.4 20.4Z"/>`,
};
function WxGlyph({ code, night }) {
  if (code == null) return null;
  const c = Number(code);
  const k = c === 0 ? (night ? "moon" : "sun") : c <= 2 ? (night ? "pmoon" : "part") : c === 3 ? "cloud"
    : c <= 48 ? "fog"
    : (c >= 71 && c <= 77) || c === 85 || c === 86 || c === 56 || c === 57 || c === 66 || c === 67 ? "snow"
    : c >= 95 ? "storm"
    : c >= 51 ? "rain" : "cloud";
  return <svg className={`wxg is-${k}`} viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={{ __html: WX_ART[k] }} />;
}

Object.assign(window, { WMO_LABEL, useNycWeather, WxGlyph });
