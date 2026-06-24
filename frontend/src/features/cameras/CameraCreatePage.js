import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
export default function CameraCreatePage() {
    const { fid, sid } = useParams();
    const navigate = useNavigate();
    const fileRef = useRef(null);
    const [name, setName] = useState("");
    const [samplingFps, setSamplingFps] = useState(0);
    const [file, setFile] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [err, setErr] = useState(null);
    const submit = async () => {
        if (!sid || !file)
            return;
        setUploading(true);
        setErr(null);
        try {
            const cam = await api.uploadCamera(sid, file, name || undefined, samplingFps);
            navigate(`/factories/${fid}/sites/${sid}/cameras/${cam.id}`);
        }
        catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        }
        finally {
            setUploading(false);
        }
    };
    return (_jsx(Panel, { title: "ADD CAMERA \u2014 FILE UPLOAD", children: _jsxs("div", { className: "flex flex-col gap-2.5", children: [_jsx("input", { placeholder: "Name (e.g. Floor cam 1)", value: name, onChange: (e) => setName(e.target.value) }), _jsxs("div", { className: "flex items-center gap-2.5 flex-wrap", children: [_jsx("label", { className: "text-text-dim text-[11px] tracking-[0.12em] uppercase", children: "Sampling fps" }), _jsxs("select", { value: samplingFps, onChange: (e) => setSamplingFps(parseFloat(e.target.value)), style: { width: 160 }, children: [_jsx("option", { value: 0, children: "Auto (native fps)" }), _jsx("option", { value: 3, children: "3 fps" }), _jsx("option", { value: 8, children: "8 fps" }), _jsx("option", { value: 15, children: "15 fps" }), _jsx("option", { value: 30, children: "30 fps" })] }), _jsx("span", { className: "text-text-dim text-[12px]", children: samplingFps === 0
                                ? "matches the source's encoded rate"
                                : "fixed sampling rate, ignores native fps" })] }), _jsxs("div", { className: "flex flex-col items-center justify-center gap-2 border-2 border-dashed border-border rounded-xl p-8 text-center text-text-dim cursor-pointer transition-colors hover:border-accent hover:text-text hover:bg-accent-10", onClick: () => fileRef.current?.click(), onDragOver: (e) => e.preventDefault(), onDrop: (e) => {
                        e.preventDefault();
                        const f = e.dataTransfer.files?.[0];
                        if (f)
                            setFile(f);
                    }, children: [_jsx(Icon, { name: "upload_file", size: 32, className: "text-text-mute" }), file
                            ? `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`
                            : "Drop a video here or click to pick one"] }), _jsx("input", { ref: fileRef, type: "file", accept: "video/*", style: { display: "none" }, onChange: (e) => setFile(e.target.files?.[0] ?? null) }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx(Button, { tone: "ghost", size: "sm", onClick: () => navigate(-1), children: "CANCEL" }), _jsx("span", { className: "flex-1" }), _jsx(Button, { tone: "primary", size: "sm", onClick: submit, disabled: !file || uploading, children: uploading ? "UPLOADING…" : "UPLOAD & START" })] }), err && _jsx("div", { className: "text-danger text-[12px] font-mono", children: err })] }) }));
}
