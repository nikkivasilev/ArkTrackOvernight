import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";

export default function CameraCreatePage() {
  const { fid, sid } = useParams();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [samplingFps, setSamplingFps] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    if (!sid || !file) return;
    setUploading(true);
    setErr(null);
    try {
      const cam = await api.uploadCamera(sid, file, name || undefined, samplingFps);
      navigate(`/factories/${fid}/sites/${sid}/cameras/${cam.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Panel title="ADD CAMERA — FILE UPLOAD">
      <div className="flex flex-col gap-2.5">
        <input
          placeholder="Name (e.g. Floor cam 1)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="flex items-center gap-2.5 flex-wrap">
          <label className="text-text-dim text-[11px] tracking-[0.12em] uppercase">
            Sampling fps
          </label>
          <select
            value={samplingFps}
            onChange={(e) => setSamplingFps(parseFloat(e.target.value))}
            style={{ width: 160 }}
          >
            <option value={0}>Auto (native fps)</option>
            <option value={3}>3 fps</option>
            <option value={8}>8 fps</option>
            <option value={15}>15 fps</option>
            <option value={30}>30 fps</option>
          </select>
          <span className="text-text-dim text-[12px]">
            {samplingFps === 0
              ? "matches the source's encoded rate"
              : "fixed sampling rate, ignores native fps"}
          </span>
        </div>
        <div
          className="flex flex-col items-center justify-center gap-2 border-2 border-dashed border-border rounded-xl p-8 text-center text-text-dim cursor-pointer transition-colors hover:border-accent hover:text-text hover:bg-accent-10"
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) setFile(f);
          }}
        >
          <Icon name="upload_file" size={32} className="text-text-mute" />
          {file
            ? `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`
            : "Drop a video here or click to pick one"}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="video/*"
          style={{ display: "none" }}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <div className="flex items-center gap-2">
          <Button tone="ghost" size="sm" onClick={() => navigate(-1)}>CANCEL</Button>
          <span className="flex-1" />
          <Button tone="primary" size="sm" onClick={submit} disabled={!file || uploading}>
            {uploading ? "UPLOADING…" : "UPLOAD & START"}
          </Button>
        </div>
        {err && <div className="text-danger text-[12px] font-mono">{err}</div>}
      </div>
    </Panel>
  );
}
