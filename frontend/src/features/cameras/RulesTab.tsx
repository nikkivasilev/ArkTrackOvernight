import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Rule, Severity, TriggerType, Zone } from "../../api/client";
import { useCameraCtx } from "./CameraContext";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { Pill, PillTone } from "../../ui/Pill";

const STUB_TRIGGERS: TriggerType[] = ["duration", "absence"];
const ZONE_INCOMPATIBLE: TriggerType[] = ["resting_worker"];

type ScopeChoice = string; // "camera" | zone_id

function defaultParams(t: TriggerType): Record<string, unknown> {
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

function severityTone(s: Severity): PillTone {
  switch (s) {
    case "info": return "info";
    case "warn": return "warn";
    case "critical": return "danger";
  }
}

export default function RulesTab() {
  const { camera } = useCameraCtx();
  const [zones, setZones] = useState<Zone[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [scope, setScope] = useState<ScopeChoice>("camera");
  const [trigger, setTrigger] = useState<TriggerType>("detection");
  const [severity, setSeverity] = useState<Severity>("warn");
  const [params, setParams] = useState<Record<string, unknown>>(() => defaultParams("detection"));

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
    if (ZONE_INCOMPATIBLE.includes(trigger)) setScope("camera");
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
      } else {
        await api.createZoneRule(scope, payload);
      }
      setName("");
      refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [camera.id, name, trigger, severity, scope, params, refresh]);

  const toggle = useCallback(
    async (r: Rule) => {
      await api.updateRule(r.id, { enabled: !r.enabled });
      refresh();
    },
    [refresh]
  );

  const remove = useCallback(
    async (rid: string) => {
      await api.deleteRule(rid);
      refresh();
    },
    [refresh]
  );

  const zoneNameById = useMemo(() => {
    const m = new Map<string, string>();
    zones.forEach((z) => m.set(z.id, z.name));
    return m;
  }, [zones]);

  const setParam = (key: string, value: unknown) =>
    setParams((p) => ({ ...p, [key]: value }));

  return (
    <>
      <Panel title="NEW RULE" className="mb-3">
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <input
              placeholder="rule name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ flex: "1 1 200px" }}
            />
            <Label>scope</Label>
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="camera">camera</option>
              {zones.map((z) => (
                <option
                  key={z.id}
                  value={z.id}
                  disabled={ZONE_INCOMPATIBLE.includes(trigger)}
                >
                  zone: {z.name}
                </option>
              ))}
            </select>
            <Label>trigger</Label>
            <select value={trigger} onChange={(e) => setTrigger(e.target.value as TriggerType)}>
              <option value="detection">detection</option>
              <option value="count_min">count_min (at least N)</option>
              <option value="count_max">count_max (at most N)</option>
              <option value="duration">duration (stub)</option>
              <option value="absence">absence (stub)</option>
              <option value="resting_worker">resting_worker</option>
            </select>
            <Label>severity</Label>
            <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
              <option value="info">info</option>
              <option value="warn">warn</option>
              <option value="critical">critical</option>
            </select>
          </div>

          <ParamFields trigger={trigger} params={params} setParam={setParam} />

          {STUB_TRIGGERS.includes(trigger) && (
            <div className="text-amber text-[12px] flex items-center gap-1.5">
              ⚠ This trigger type is a placeholder. Rule is saved but won't fire alerts yet (Phase 2/3).
            </div>
          )}

          <div className="flex items-center">
            <span className="flex-1" />
            <Button tone="primary" size="sm" onClick={create}>CREATE RULE</Button>
          </div>
          {err && <div className="text-danger text-[12px] font-mono">{err}</div>}
        </div>
      </Panel>

      <Panel title={`RULES (${rules.length})`}>
        {rules.length === 0 ? (
          <div className="text-text-dim text-[13px]">No rules yet.</div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {rules.map((r) => {
              const scopeLabel = r.zone_id ? `zone: ${zoneNameById.get(r.zone_id) ?? "?"}` : "camera";
              const stub = STUB_TRIGGERS.includes(r.trigger_type);
              return (
                <div
                  key={r.id}
                  className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-border bg-surface-high/20 hover:bg-surface-high/40 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={r.enabled}
                    onChange={() => toggle(r)}
                    title="enabled"
                  />
                  <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium text-text truncate">{r.name}</span>
                      <Pill tone={severityTone(r.severity)}>{r.severity}</Pill>
                      {stub && <Pill tone="warn">stub</Pill>}
                    </div>
                    <div className="text-text-dim text-[11px] font-mono truncate">
                      {r.trigger_type} · {scopeLabel} · {JSON.stringify(r.params)}
                    </div>
                  </div>
                  <Button tone="danger" size="sm" onClick={() => remove(r.id)}>DELETE</Button>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-text-dim text-[11px] tracking-[0.12em] uppercase">
      {children}
    </label>
  );
}

function ParamFields({
  trigger,
  params,
  setParam,
}: {
  trigger: TriggerType;
  params: Record<string, unknown>;
  setParam: (k: string, v: unknown) => void;
}) {
  const numericInput = (key: string, step = 0.05, min: number | undefined = undefined, width = 100) => (
    <input
      type="number"
      step={step}
      min={min}
      value={String(params[key] ?? 0)}
      onChange={(e) => setParam(key, parseFloat(e.target.value))}
      style={{ width }}
    />
  );
  const intInput = (key: string, width = 80) => (
    <input
      type="number"
      step={1}
      min={0}
      value={String(params[key] ?? 0)}
      onChange={(e) => setParam(key, parseInt(e.target.value, 10) || 0)}
      style={{ width }}
    />
  );
  const classInput = () => (
    <input
      value={String(params.target_class ?? "person")}
      onChange={(e) => setParam("target_class", e.target.value)}
      style={{ width: 120 }}
    />
  );

  if (trigger === "detection") {
    return (
      <div className="flex items-center gap-2.5">
        <Label>class</Label>{classInput()}
        <Label>min conf</Label>{numericInput("min_confidence")}
      </div>
    );
  }
  if (trigger === "count_min" || trigger === "count_max") {
    return (
      <div className="flex items-center gap-2.5">
        <Label>class</Label>{classInput()}
        <Label>threshold</Label>{intInput("threshold")}
        <Label>min conf</Label>{numericInput("min_confidence")}
      </div>
    );
  }
  if (trigger === "duration") {
    return (
      <div className="flex items-center gap-2.5">
        <Label>class</Label>{classInput()}
        <Label>min conf</Label>{numericInput("min_confidence")}
        <Label>seconds</Label>{numericInput("duration_seconds", 1, 0)}
      </div>
    );
  }
  if (trigger === "absence") {
    return (
      <div className="flex items-center gap-2.5">
        <Label>class</Label>{classInput()}
        <Label>seconds</Label>{numericInput("duration_seconds", 1, 0)}
      </div>
    );
  }
  // resting_worker: capture a clip when a worker is classified resting/idle
  // (sitting/sleeping/standing_idle/on_phone) for a sustained period.
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <Label>pre-roll s</Label>{numericInput("pre_roll_s", 1, 0, 70)}
      <Label>min resting s</Label>{numericInput("min_resting_s", 1, 0, 70)}
      <Label>end grace s</Label>{numericInput("end_grace_s", 1, 0, 70)}
      <Label>max clip s</Label>{numericInput("max_clip_s", 5, 0, 70)}
      <Label>min clip s</Label>{numericInput("min_clip_s", 1, 0, 70)}
      <Label>crop pad px</Label>{intInput("crop_pad_px", 70)}
    </div>
  );
}
