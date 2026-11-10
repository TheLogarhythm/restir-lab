import { useId, useState, type ReactNode } from "react";
import { Modal } from "./Modal";
import "../styles/restir-pipeline.css";

type NodeProps = {
  x: number; y: number; w: number; h: number;
  title: ReactNode; lines?: ReactNode[]; variant?: "input" | "result" | "normal"; changed?: boolean;
};

function FlowNode({ x, y, w, h, title, lines = [], variant = "normal", changed = false }: NodeProps) {
  return <g className={`flow-node flow-node-${variant}${changed ? " flow-node-changed" : ""}`}>
    <rect x={x} y={y} width={w} height={h} rx="8" />
    <text x={x + w / 2} y={y + (lines.length ? 18 : h / 2 + 5)} textAnchor="middle">
      <tspan className="flow-node-title" x={x + w / 2}>{title}</tspan>
      {lines.map((line, i) => <tspan key={i} x={x + w / 2} dy="17">{line}</tspan>)}
    </text>
  </g>;
}

function Decision({ x, y, title, lines = [] }: { x: number; y: number; title: string; lines?: string[] }) {
  return <g className="flow-decision">
    <path d={`M ${x} ${y} l 90 32 l -90 32 l -90 -32 Z`} />
    <text x={x} y={y + (lines.length ? 28 : 37)} textAnchor="middle">
      <tspan className="flow-node-title" x={x}>{title}</tspan>
      {lines.map((line, i) => <tspan key={i} x={x} dy="17">{line}</tspan>)}
    </text>
  </g>;
}

function MathSub({ base, sub }: { base: string; sub: string }) {
  return <tspan className="flow-math">{base}<tspan baselineShift="sub" fontSize="11">{sub}</tspan></tspan>;
}

function CandidateWeightFormula() {
  return <tspan className="flow-formula" aria-label="w sub i equals p hat sub q of x sub i divided by p of x sub i">
    <tspan>w</tspan><tspan baselineShift="sub" fontSize="11">i</tspan>
    <tspan> = </tspan>
    <tspan>p̂</tspan><tspan baselineShift="sub" fontSize="11">q</tspan>
    <tspan>(x</tspan><tspan baselineShift="sub" fontSize="11">i</tspan>
    <tspan>) / p(x</tspan><tspan baselineShift="sub" fontSize="11">i</tspan><tspan>)</tspan>
  </tspan>;
}

function PipelineChart() {
  return <div className="pipeline-chart-scroll" tabIndex={0} aria-label="Scrollable ReSTIR DI flowchart">
    <svg className="pipeline-chart" viewBox="0 0 1200 535" role="img" aria-label="ReSTIR DI flowchart" aria-describedby="pipeline-chart-description">
      <desc id="pipeline-chart-description">Initial candidates are weighted and sampled into a reservoir, then checked for visibility. The current reservoir is merged with valid reprojected history, then with nearby reservoirs. Spatial reuse may repeat. The final reservoir is used for shading and stored for the next frame.</desc>
      <defs>
        <marker id="pipeline-arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
      </defs>

      {/* Equal-width stages; node centers follow the same 80-unit row grid. */}
      <rect className="flow-group flow-group-initial" x="20" y="20" width="360" height="440" rx="16" />
      <text className="flow-group-title" x="40" y="45">01 Initial Sampling / RIS</text>
      <rect className="flow-group flow-group-temporal" x="420" y="20" width="360" height="440" rx="16" />
      <text className="flow-group-title" x="440" y="45">02 Temporal Reuse</text>
      <rect className="flow-group flow-group-spatial" x="820" y="20" width="360" height="440" rx="16" />
      <text className="flow-group-title" x="840" y="45">03 Spatial Reuse</text>

      <g className="flow-edges" markerEnd="url(#pipeline-arrowhead)">
        <path d="M200 115 V147" />
        <path d="M200 195 V227" />
        <path d="M200 275 V307" />
        <path d="M200 355 V377" />

        {/* Both visibility branches join in the gutter before entering temporal reuse. */}
        <path d="M291 412 H400" markerEnd="none" />
        <path d="M200 445 V480 H400 V412" markerEnd="none" />
        <path d="M400 412 V332 H477" />

        <path d="M600 115 V147" />
        <path d="M600 195 V217" />
        <path d="M600 285 V307" />
        <path d="M691 252 H750 V362 H690 V387" />
        <path d="M600 355 V387" />
        <path d="M721 412 H800 V252 H877" />

        <path d="M1000 115 V147" />
        <path d="M1000 195 V227" />
        <path d="M1000 275 V297" />
        <path d="M1091 332 H1150 V172 H1123" />
        <path d="M1000 365 V387" />
        <path d="M1000 435 V467" />
        <path className="flow-edge-feedback" d="M1121 412 H1190 V8 H750 V92 H723" />
      </g>
      <circle className="flow-junction" cx="400" cy="412" r="3" />
      <g className="flow-edge-labels">
        <text x="315" y="401">Yes</text>
        <text x="232" y="471">No: weight = 0</text>
        <text x="611" y="300">Yes</text>
        <text x="737" y="287" textAnchor="end"><tspan x="737">No</tspan><tspan x="737" dy="16">keep current</tspan></text>
        <text x="1105" y="321">Yes</text>
        <text x="1011" y="380">No</text>
        <text className="flow-feedback-label" x="875" y="18">Used by the next frame</text>
      </g>

      <FlowNode x={80} y={70} w={240} h={44} title="Generate M light candidates" lines={["pixel q, proposal p(xᵢ)"]} variant="input" />
      <FlowNode x={80} y={150} w={240} h={44} title="Compute candidate weights" lines={[<CandidateWeightFormula key="weight-formula" />]} />
      <FlowNode x={80} y={230} w={240} h={44} title="Weighted reservoir sampling" />
      <FlowNode x={80} y={310} w={240} h={44} title="Initial reservoir R₀" lines={["sample y, weights, count M"]} variant="result" />
      <Decision x={200} y={380} title="Selected sample" lines={[" visible?"]} />

      <FlowNode x={480} y={70} w={240} h={44} title="Previous frame's final" lines={[" reservoir buffer"]} variant="input" />
      <FlowNode x={480} y={150} w={240} h={44} title="Reproject pixel" />
      <Decision x={600} y={220} title="Is the history" lines={[" valid for reuse?"]} />
      <FlowNode x={480} y={310} w={240} h={44} title="Reweight & merge reservoirs" />
      <FlowNode x={480} y={390} w={240} h={44} title="Temporal reservoir Rₜ" variant="result" />

      <FlowNode x={880} y={70} w={240} h={44} title="Neighboring reservoirs" variant="input" />
      <FlowNode x={880} y={150} w={240} h={44} title="Select valid neighbors" />
      <FlowNode x={880} y={230} w={240} h={44} title="Reweight & merge reservoirs" />
      <Decision x={1000} y={300} title="More spatial" lines={[" reuse passes?"]} />
      <FlowNode x={880} y={390} w={240} h={44} title="Final reservoir Rfinal" variant="result" />
      <FlowNode x={880} y={470} w={240} h={44} title="Visibility & shading" lines={["direct lighting output"]} variant="result" />
    </svg>
  </div>;
}

function GIPipelineChart() {
  return <div className="pipeline-chart-scroll" tabIndex={0} aria-label="Scrollable ReSTIR GI flowchart">
    <svg className="pipeline-chart" viewBox="0 0 1200 535" role="img" aria-label="ReSTIR GI flowchart" aria-describedby="gi-pipeline-description">
      <desc id="gi-pipeline-description">Unlike DI light sampling, GI traces indirect rays and stores secondary-surface geometry and radiance. Temporal reuse combines fresh samples with valid reprojected history. Spatial reuse normally reads nearby temporal reservoirs. When sample count is low it can also reuse spatial reservoirs, reducing noise but risking accumulated bias. It reconnects to a shared sample point, checks visibility, and applies a Jacobian correction before reservoir merging. The temporal reservoir is saved for the next frame; the spatial reservoir is used for indirect lighting.</desc>
      <defs>
        <marker className="flow-marker" id="gi-pipeline-arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
        <marker id="gi-optional-arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
      </defs>
      <rect className="flow-group flow-group-initial" x="20" y="20" width="360" height="440" rx="16" />
      <text className="flow-group-title" x="40" y="45">01 Initial Path Sample</text>
      <rect className="flow-group flow-group-temporal" x="420" y="20" width="360" height="440" rx="16" />
      <text className="flow-group-title" x="440" y="45">02 Temporal Reuse</text>
      <rect className="flow-group flow-group-spatial" x="820" y="20" width="360" height="440" rx="16" />
      <text className="flow-group-title" x="840" y="45">03 Spatial Reuse</text>

      <g className="flow-edges" markerEnd="url(#gi-pipeline-arrowhead)">
        <path d="M200 115 V147" />
        <path d="M200 195 V227" />
        <path d="M200 275 V307" />
        <path d="M200 355 V387" />
        <path d="M321 412 H400 V332 H477" />

        <path d="M600 115 V147" />
        <path d="M600 195 V217" />
        <path d="M600 285 V307" />
        <path d="M691 252 H750 V362 H690 V387" />
        <path d="M600 355 V387" />
        <path d="M721 412 H800 V92 H832" />

        {/* Solid is the default; dashed is the additional low-count input. */}
        <path d="M912.5 115 V130 H925 V147" />
        <path className="flow-edge-optional" markerEnd="url(#gi-optional-arrowhead)" d="M1087.5 115 V130 H1075 V147" />
        <path d="M1000 195 V227" />
        <path d="M1000 275 V297" />
        <path d="M1091 332 H1150 V172 H1123" />
        <path d="M1000 365 V387" />
        <path d="M1000 435 V467" />

        {/* Original GI keeps temporal history separate from the spatial shading result. */}
        <path className="flow-edge-feedback" d="M600 435 V480 H10 V8 H750 V92 H723" />
      </g>
      <g className="flow-edge-labels">
        <text x="611" y="300">Yes</text>
        <text x="737" y="287" textAnchor="end"><tspan x="737">No</tspan><tspan x="737" dy="16">keep current</tspan></text>
        <text x="1105" y="321">Yes</text>
        <text x="1011" y="380">No</text>
        <text className="flow-feedback-label" x="45" y="18">Used by the next frame</text>
      </g>

      <FlowNode x={80} y={70} w={240} h={44} title="Trace an indirect ray" lines={["sample a direction at pixel q"]} variant="input" changed />
      <FlowNode x={80} y={150} w={240} h={44} title="Find secondary surface" lines={[<>sample point <MathSub base="x" sub="s" /> and normal <MathSub base="n" sub="s" /></>]} changed />
      <FlowNode x={80} y={230} w={240} h={44} title="Estimate secondary radiance" lines={[<>continue path tracing from <MathSub base="x" sub="s" /></>]} changed />
      <FlowNode x={80} y={310} w={240} h={44} title="Initial GI sample" lines={[<><MathSub base="x" sub="s" />, <MathSub base="n" sub="s" />, radiance and direction PDF</>]} changed />
      <FlowNode x={80} y={390} w={240} h={44} title={<>Initialize reservoir <MathSub base="R" sub="0" /></>} lines={["fresh path sample and RIS weight"]} variant="result" />

      <FlowNode x={480} y={70} w={240} h={44} title="Previous temporal reservoir" variant="input" changed />
      <FlowNode x={480} y={150} w={240} h={44} title="Reproject pixel" lines={["motion vectors"]} />
      <Decision x={600} y={220} title="Is the history" lines={[" valid for reuse?"]} />
      <FlowNode x={480} y={310} w={240} h={44} title="Update temporal reservoir" lines={["fresh + valid historical sample"]} />
      <FlowNode x={480} y={390} w={240} h={44} title={<>Temporal reservoir <MathSub base="R" sub="t" /></>} variant="result" />

      <FlowNode x={835} y={70} w={155} h={44} title="Temporal reservoir" lines={["neighbor (default)"]} variant="input" />
      <FlowNode x={1010} y={70} w={155} h={44} title="Spatial reservoir" lines={["neighbor (low count)"]} variant="input" />
      <FlowNode x={880} y={150} w={240} h={44} title="Reconnect to sample point" lines={["check geometry and visibility"]} changed />
      <FlowNode x={880} y={230} w={240} h={44} title="Jacobian weight & merge" lines={["correct PDF at the receiving pixel"]} changed />
      <Decision x={1000} y={300} title="More neighbor" lines={[" reservoirs?"]} />
      <FlowNode x={880} y={390} w={240} h={44} title="Final spatial reservoir" variant="result" />
      <FlowNode x={880} y={470} w={240} h={44} title="Shade indirect lighting" lines={["BRDF, cosine, radiance and weight"]} variant="result" changed />
    </svg>
  </div>;
}

export function RestirPipeline({ method = "di" }: { method?: "di" | "gi" }) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const isGI = method === "gi";
  const name = isGI ? "ReSTIR GI" : "ReSTIR DI";
  const source = isGI
    ? "https://d1qx31qr3h6wln.cloudfront.net/publications/ReSTIR%20GI.pdf"
    : "https://research.nvidia.com/sites/default/files/pubs/2020-07_Spatiotemporal-reservoir-resampling/ReSTIR.pdf";

  return (
    <section className="pipeline-intro">
      <h3>Algorithm pipeline</h3>
      <p>{isGI
        ? "Follow indirect paths through sampling, reconnection and reservoir reuse."
        : "Follow a light sample from initial sampling through spatiotemporal reuse and shading."}</p>
      <button className="pipeline-trigger" onClick={() => setOpen(true)}>
        View {name} pipeline <span aria-hidden="true">↗</span>
      </button>
      {open && (
        <Modal titleId={titleId} className={`pipeline-dialog${isGI ? " pipeline-dialog-gi" : ""}`} onClose={() => setOpen(false)}>
          <button className="dialog-close icon-button" aria-label="Close pipeline" onClick={() => setOpen(false)}>×</button>
          <div className="pipeline-heading">
            <span className="pipeline-eyebrow">ORIGINAL {name.toUpperCase()} {isGI ? "2021" : "2020"}</span>
            <h2 id={titleId}>{name} pipeline</h2>
          </div>
          {isGI && <p className="pipeline-comparison"><span className="pipeline-change-key" aria-hidden="true" />GI reuses secondary-surface radiance. Highlighted steps differ from DI.</p>}
          <p className="pipeline-scroll-hint">Scroll horizontally to explore the full diagram on a narrow screen.</p>
          {isGI ? <GIPipelineChart /> : <PipelineChart />}
          {isGI && <p className="pipeline-gi-reuse-note">Solid green: reuse neighboring temporal reservoirs by default. Dashed amber: also reuse neighboring spatial reservoirs when sample count is low; repeated reuse may accumulate bias.</p>}
          <div className="pipeline-text-alternative">
            <h3>{isGI ? "Initial path sample" : "Initial sampling / RIS"}</h3>
            <p>{isGI
              ? "Trace an indirect ray from the primary surface to a secondary point, estimate radiance by path tracing, and initialize a GI reservoir. DI instead samples light sources."
              : "Generate and weight candidates, then select one with weighted reservoir sampling. Test its visibility and set the reuse weight to zero if occluded."}</p>
            <h3>Temporal reuse</h3>
            <p>{isGI ? "Reproject to the previous frame. When history is valid, combine the fresh and historical samples; otherwise keep the current sample." : "Reproject to the previous frame. When history is valid, re-evaluate its sample at the current pixel and merge the historical and current reservoirs; otherwise skip history."}</p>
            <h3>Spatial reuse</h3>
            <p>{isGI
              ? "Normally reuse nearby temporal reservoirs. When sample count is low, spatial reservoirs can also be reused to reduce noise, though repeated spatial reuse can accumulate bias. Reconnect to secondary points, check surface compatibility and connection visibility, apply the solid-angle Jacobian correction, and resample. Use the spatial result for indirect lighting and retain the temporal result for next-frame history."
              : "Select valid neighbors, re-evaluate and merge their samples, and repeat the pass if needed. Shade using the final reservoir, which is stored for the next frame."}</p>
          </div>
          <div className="pipeline-notes">
            <a href={source} target="_blank" rel="noreferrer">Read the original paper ({isGI ? "Figure 4, Algorithms 2–4" : "Algorithms 3–5"}) ↗</a>
          </div>
        </Modal>
      )}
    </section>
  );
}
