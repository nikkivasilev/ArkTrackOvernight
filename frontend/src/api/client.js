const BASE = "/api";
async function json(resp) {
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
    }
    return resp.json();
}
async function okOnly(resp) {
    if (!resp.ok)
        throw new Error(await resp.text());
}
const jsonHeaders = { "Content-Type": "application/json" };
export const api = {
    // Factories
    listFactories: () => fetch(`${BASE}/factories`).then((json)),
    getFactory: (id) => fetch(`${BASE}/factories/${id}`).then((json)),
    createFactory: (payload) => fetch(`${BASE}/factories`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then((json)),
    deleteFactory: (id) => fetch(`${BASE}/factories/${id}`, { method: "DELETE" }).then(okOnly),
    // Sites
    listSitesForFactory: (fid) => fetch(`${BASE}/factories/${fid}/sites`).then((json)),
    getSite: (sid) => fetch(`${BASE}/sites/${sid}`).then((json)),
    createSite: (fid, payload) => fetch(`${BASE}/factories/${fid}/sites`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then((json)),
    deleteSite: (sid) => fetch(`${BASE}/sites/${sid}`, { method: "DELETE" }).then(okOnly),
    // Cameras
    listCamerasForSite: (sid) => fetch(`${BASE}/sites/${sid}/cameras`).then((json)),
    listAllCameras: () => fetch(`${BASE}/cameras`).then((json)),
    getCamera: (cid) => fetch(`${BASE}/cameras/${cid}`).then((json)),
    uploadCamera: (sid, file, name, samplingFps) => {
        const fd = new FormData();
        fd.append("file", file);
        if (name)
            fd.append("name", name);
        if (samplingFps !== undefined)
            fd.append("sampling_fps", String(samplingFps));
        return fetch(`${BASE}/sites/${sid}/cameras`, { method: "POST", body: fd }).then((json));
    },
    startCamera: (cid) => fetch(`${BASE}/cameras/${cid}/start`, { method: "POST" }).then((json)),
    cancelCamera: (cid) => fetch(`${BASE}/cameras/${cid}/cancel`, { method: "POST" }).then((json)),
    deleteCamera: (cid) => fetch(`${BASE}/cameras/${cid}`, { method: "DELETE" }).then(okOnly),
    frameUrl: (cid, t) => `${BASE}/cameras/${cid}/frame?t=${encodeURIComponent(t)}`,
    liveUrl: (cid) => `${BASE}/cameras/${cid}/live.mjpg`,
    // Zones
    listZones: (cid) => fetch(`${BASE}/cameras/${cid}/zones`).then((json)),
    createZone: (cid, name, polygon, excluded = false) => fetch(`${BASE}/cameras/${cid}/zones`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ name, polygon, excluded }) }).then((json)),
    updateZone: (zid, patch) => fetch(`${BASE}/zones/${zid}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(patch) }).then((json)),
    deleteZone: (zid) => fetch(`${BASE}/zones/${zid}`, { method: "DELETE" }).then(okOnly),
    // Rules
    listRulesForCamera: (cid) => fetch(`${BASE}/cameras/${cid}/rules`).then((json)),
    createCameraRule: (cid, payload) => fetch(`${BASE}/cameras/${cid}/rules`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then((json)),
    createZoneRule: (zid, payload) => fetch(`${BASE}/zones/${zid}/rules`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then((json)),
    updateRule: (rid, patch) => fetch(`${BASE}/rules/${rid}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(patch) }).then((json)),
    deleteRule: (rid) => fetch(`${BASE}/rules/${rid}`, { method: "DELETE" }).then(okOnly),
    // Alerts
    listAlerts: (params = {}) => {
        const u = new URLSearchParams();
        if (params.factory_id)
            u.set("factory_id", params.factory_id);
        if (params.site_id)
            u.set("site_id", params.site_id);
        if (params.camera_id)
            u.set("camera_id", params.camera_id);
        if (params.acknowledged !== undefined)
            u.set("acknowledged", String(params.acknowledged));
        if (params.limit)
            u.set("limit", String(params.limit));
        return fetch(`${BASE}/alerts?${u.toString()}`).then((json));
    },
    ackAlert: (aid) => fetch(`${BASE}/alerts/${aid}/ack`, { method: "POST" }).then((json)),
    deleteAlert: (aid) => fetch(`${BASE}/alerts/${aid}`, { method: "DELETE" }).then((r) => {
        if (!r.ok)
            throw new Error(`delete failed: ${r.status}`);
    }),
    alertThumbnailUrl: (aid) => `${BASE}/alerts/${aid}/thumbnail`,
    alertClipUrl: (aid) => `${BASE}/alerts/${aid}/clip`,
    // Live-pipeline controls (Phase 1: d-fine / motion / overlay)
    setCameraModules: (cid, modules) => fetch(`${BASE}/cameras/${cid}/modules`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify(modules),
    }).then((json)),
    // Offline reports
    getReport: (fid, period, date) => {
        const u = new URLSearchParams({ period });
        if (date)
            u.set("date", date);
        return fetch(`${BASE}/factories/${fid}/report?${u.toString()}`).then((json));
    },
    reportPdfUrl: (fid, period, date) => {
        const u = new URLSearchParams({ period });
        if (date)
            u.set("date", date);
        return `${BASE}/factories/${fid}/report.pdf?${u.toString()}`;
    },
    // Processed-recording ledger
    listRecordings: (fid, status) => {
        const u = new URLSearchParams();
        if (status)
            u.set("status", status);
        const qs = u.toString();
        return fetch(`${BASE}/factories/${fid}/recordings${qs ? `?${qs}` : ""}`).then((json));
    },
};
