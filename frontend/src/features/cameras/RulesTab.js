import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { useCameraCtx } from "./CameraContext";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
const STUB_TRIGGERS = ["duration", "absence"];
const ZONE_INCOMPATIBLE = ["resting_worker"];
function defaultParams(t) {
    switch (t) {
        case "detection":
            return { target_class: "person", min_confidence: 0.5 };
        case "count_min":
        case "count_max":
            return { target_class: "person", threshold: 3, min_confidence: 0.5 };
        case "duration":
            return { target_class: "person", min_confidence: 0.5, duration_seconds: 10 };
        case "absence":
            return { target_class: "person", duration_seconds: 30 };
        case "resting_worker":
            return { pre_roll_s: 3, min_resting_s: 5, end_grace_s: 2, max_clip_s: 120, min_clip_s: 10, crop_pad_px: 120 };
    }
}
function severityTone(s) {
    switch (s) {
        case "info": return "info";
        case "warn": return "warn";
        case "critical": return "danger";
    }
}
export default function RulesTab() {
    const { camera } = useCameraCtx();
    const [zones, setZones] = useState([]);
    const [rules, setRules] = useState([]);
    const [err, setErr] = useState(null);
    const [name, setName] = useState("");
    const [scope, setScope] = useState("camera");
    const [trigger, setTrigger] = useState("detection");
    const [severity, setSeverity] = useState("warn");
    const [params, setParams] = useState(() => defaultParams("detection"));
    const refresh = useCallback(async () => {
        const [zs, rs] = await Promise.all([
            api.listZones(camera.id),
            api.listRulesForCamera(camera.id),
        ]);
        setZones(zs);
        setRules(rs);
    }, [camera.id]);
    useEffect(() => {
        refresh().catch(console.error);
    }, [refresh]);
    useEffect(() => {
        setParams(defaultParams(trigger));
        if (ZONE_INCOMPATIBLE.includes(trigger))
            setScope("camera");
    }, [trigger]);
    const create = useCallback(async () => {
        setErr(null);
        try {
            const payload = {
                name: name.trim() || `${trigger}-rule`,
                trigger_type: trigger,
                severity,
                params,
                enabled: true,
            };
            if (scope === "camera") {
                await api.createCameraRule(camera.id, payload);
            }
            else {
                await api.createZoneRule(scope, payload);
            }
            setName("");
            refresh();
        }
        catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        }
    }, [camera.id, name, trigger, severity, scope, params, refresh]);
    const toggle = useCallback(async (r) => {
        await api.updateRule(r.id, { enabled: !r.enabled });
        refresh();
    }, [refresh]);
    const remove = useCallback(async (rid) => {
        await api.deleteRule(rid);
        refresh();
    }, [refresh]);
    const zoneNameById = useMemo(() => {
        const m = new Map();
        zones.forEach((z) => m.set(z.id, z.name));
        return m;
    }, [zones]);
    const setParam = (key, value) => setParams((p) => ({ ...p, [key]: value }));
    return (_jsxs(_Fragment, { children: [_jsx(Panel, { title: "NEW RULE", className: "mb-3", children: _jsxs("div", { className: "flex flex-col gap-2.5", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2.5", children: [_jsx("input", { placeholder: "rule name", value: name, onChange: (e) => setName(e.target.value), style: { flex: "1 1 200px" } }), _jsx(Label, { children: "scope" }), _jsxs("select", { value: scope, onChange: (e) => setScope(e.target.value), children: [_jsx("option", { value: "camera", children: "camera" }), zones.map((z) => (_jsxs("option", { value: z.id, disabled: ZONE_INCOMPATIBLE.includes(trigger), children: ["zone: ", z.name] }, z.id)))] }), _jsx(Label, { children: "trigger" }), _jsxs("select", { value: trigger, onChange: (e) => setTrigger(e.target.value), children: [_jsx("option", { value: "detection", children: "detection" }), _jsx("option", { value: "count_min", children: "count_min (at least N)" }), _jsx("option", { value: "count_max", children: "count_max (at most N)" }), _jsx("option", { value: "duration", children: "duration (stub)" }), _jsx("option", { value: "absence", children: "absence (stub)" }), _jsx("option", { value: "resting_worker", children: "resting_worker" })] }), _jsx(Label, { children: "severity" }), _jsxs("select", { value: severity, onChange: (e) => setSeverity(e.target.value), children: [_jsx("option", { value: "info", children: "info" }), _jsx("option", { value: "warn", children: "warn" }), _jsx("option", { value: "critical", children: "critical" })] })] }), _jsx(ParamFields, { trigger: trigger, params: params, setParam: setParam }), STUB_TRIGGERS.includes(trigger) && (_jsx("div", { className: "text-amber text-[12px] flex items-center gap-1.5", children: "\u26A0 This trigger type is a placeholder. Rule is saved but won't fire alerts yet (Phase 2/3)." })), _jsxs("div", { className: "flex items-center", children: [_jsx("span", { className: "flex-1" }), _jsx(Button, { tone: "primary", size: "sm", onClick: create, children: "CREATE RULE" })] }), err && _jsx("div", { className: "text-danger text-[12px] font-mono", children: err })] }) }), _jsx(Panel, { title: `RULES (${rules.length})`, children: rules.length === 0 ? (_jsx("div", { className: "text-text-dim text-[13px]", children: "No rules yet." })) : (_jsx("div", { className: "flex flex-col gap-1.5", children: rules.map((r) => {
                        const scopeLabel = r.zone_id ? `zone: ${zoneNameById.get(r.zone_id) ?? "?"}` : "camera";
                        const stub = STUB_TRIGGERS.includes(r.trigger_type);
                        return (_jsxs("div", { className: "flex items-center gap-3 px-4 py-2.5 rounded-lg border border-border bg-surface-high/20 hover:bg-surface-high/40 transition-colors", children: [_jsx("input", { type: "checkbox", checked: r.enabled, onChange: () => toggle(r), title: "enabled" }), _jsxs("div", { className: "flex flex-col gap-0.5 flex-1 min-w-0", children: [_jsxs("div", { className: "flex items-center gap-1.5", children: [_jsx("span", { className: "font-medium text-text truncate", children: r.name }), _jsx(Pill, { tone: severityTone(r.severity), children: r.severity }), stub && _jsx(Pill, { tone: "warn", children: "stub" })] }), _jsxs("div", { className: "text-text-dim text-[11px] font-mono truncate", children: [r.trigger_type, " \u00B7 ", scopeLabel, " \u00B7 ", JSON.stringify(r.params)] })] }), _jsx(Button, { tone: "danger", size: "sm", onClick: () => remove(r.id), children: "DELETE" })] }, r.id));
                    }) })) })] }));
}
function Label({ children }) {
    return (_jsx("label", { className: "text-text-dim text-[11px] tracking-[0.12em] uppercase", children: children }));
}
function ParamFields({ trigger, params, setParam, }) {
    const numericInput = (key, step = 0.05, min = undefined, width = 100) => (_jsx("input", { type: "number", step: step, min: min, value: String(params[key] ?? 0), onChange: (e) => setParam(key, parseFloat(e.target.value)), style: { width } }));
    const intInput = (key, width = 80) => (_jsx("input", { type: "number", step: 1, min: 0, value: String(params[key] ?? 0), onChange: (e) => setParam(key, parseInt(e.target.value, 10) || 0), style: { width } }));
    const classInput = () => (_jsx("input", { value: String(params.target_class ?? "person"), onChange: (e) => setParam("target_class", e.target.value), style: { width: 120 } }));
    if (trigger === "detection") {
        return (_jsxs("div", { className: "flex items-center gap-2.5", children: [_jsx(Label, { children: "class" }), classInput(), _jsx(Label, { children: "min conf" }), numericInput("min_confidence")] }));
    }
    if (trigger === "count_min" || trigger === "count_max") {
        return (_jsxs("div", { className: "flex items-center gap-2.5", children: [_jsx(Label, { children: "class" }), classInput(), _jsx(Label, { children: "threshold" }), intInput("threshold"), _jsx(Label, { children: "min conf" }), numericInput("min_confidence")] }));
    }
    if (trigger === "duration") {
        return (_jsxs("div", { className: "flex items-center gap-2.5", children: [_jsx(Label, { children: "class" }), classInput(), _jsx(Label, { children: "min conf" }), numericInput("min_confidence"), _jsx(Label, { children: "seconds" }), numericInput("duration_seconds", 1, 0)] }));
    }
    if (trigger === "absence") {
        return (_jsxs("div", { className: "flex items-center gap-2.5", children: [_jsx(Label, { children: "class" }), classInput(), _jsx(Label, { children: "seconds" }), numericInput("duration_seconds", 1, 0)] }));
    }
    // resting_worker: capture a clip when a worker is classified resting/idle
    // (sitting/sleeping/standing_idle/on_phone) for a sustained period.
    return (_jsxs("div", { className: "flex flex-wrap items-center gap-2.5", children: [_jsx(Label, { children: "pre-roll s" }), numericInput("pre_roll_s", 1, 0, 70), _jsx(Label, { children: "min resting s" }), numericInput("min_resting_s", 1, 0, 70), _jsx(Label, { children: "end grace s" }), numericInput("end_grace_s", 1, 0, 70), _jsx(Label, { children: "max clip s" }), numericInput("max_clip_s", 5, 0, 70), _jsx(Label, { children: "min clip s" }), numericInput("min_clip_s", 1, 0, 70), _jsx(Label, { children: "crop pad px" }), intInput("crop_pad_px", 70)] }));
}
