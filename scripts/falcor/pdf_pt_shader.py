"""Compose the first-hop statistics and pairwise-MIS overlay for private point-PT runtimes.

Only the existing reflected structured buffers grow. Independent per-pixel fields
are explicitly carried across pass writes, never chosen by a reservoir merge.
"""
from pathlib import Path

from . import pdf_pt_mis

HERE = Path(__file__).parent
VMF = HERE.parent / 'run/rtxdi_experiments/PdfSimilarityMath.h'
PT = 'shaders/RenderPasses/PathTracer/'
MODULE = 'shaders/ReSTIRPathTracing/'
FILES = tuple(MODULE + n for n in (*pdf_pt_mis.FILES, 'TemporalResampling.cs.slang',
                                    'ReSTIRPT.slang', 'FetchDenoiserData.cs.slang')) + (
    PT + 'GeneratePaths.cs.slang', PT + 'PathTracer.slang')
PROFILES = ('normal', 'one', 'zero', 'center', 'observe', 'native')


def source_files():
    return (Path(__file__), Path(pdf_pt_mis.__file__), pdf_pt_mis.CORE, VMF,
            HERE / 'pdf_pt_direction.h', HERE / 'pdf_pt_history.slang')


def once(source, anchor, replacement):
    if source.count(anchor) != 1:
        raise ValueError('Unexpected PDF PT shader anchor: ' + anchor)
    return source.replace(anchor, replacement, 1)


def _diagnostic_outputs(source, native):
    anchor = 'PathReservoir centralReservoir = reservoirs[centralOffset];'
    code = """
#if FETCH_NRD_DATA_PASS
        bool surface = HitInfo(vbuffer[pixel]).isValid();
        outputEmission[pixel] = surface ? float4(centralReservoir.M, centralReservoir.weight,
            centralReservoir.weight > 0.f ? PathRISState::toScalar(centralReservoir.integrand) : 0.f, COUNT) : 0.f;
        EXTRA
        return;
#endif
"""
    extra = 'outputDiffuseRadianceHitDist[pixel] = 0.f;' if native else """
        outputDiffuseRadianceHitDist[pixel] = surface ? centralReservoir.labMoment : 0.f;
        outputSpecularRadianceHitDist[pixel] = surface ? centralReservoir.labPair : 0.f;
        outputResidualRadianceHitDist[pixel] = surface ? centralReservoir.labInitialAudit : 0.f;
"""
    return once(source, anchor, anchor + code.replace('COUNT', '0.f' if native else
                'centralReservoir.labCount').replace('EXTRA', extra))


def build_overlay(sources, parameters, profile='normal'):
    from .pdf_pt_overlay import validate_parameters

    parameters = validate_parameters(parameters)
    profile_id = PROFILES.index(profile)
    data = {name: value.replace('\r\n', '\n') for name, value in sources.items()}

    def change(name, anchor, new):
        data[name] = once(data[name], anchor, new)

    name = MODULE + 'FetchDenoiserData.cs.slang'
    if profile != 'normal':
        data[name] = _diagnostic_outputs(data[name], profile == 'native')
    if profile != 'native':
        subset = {name: data[MODULE + name] for name in pdf_pt_mis.FILES}
        data.update({MODULE + name: value for name, value in pdf_pt_mis.apply(subset).items()})
        name = MODULE + 'PathReservoir.slang'
        params = (f'static const int kLabPdfProfile = {profile_id};\n'
                  f'static const float kLabPdfHistoryLimit = {parameters["history_limit"]}.f;\n'
                  f'static const float kLabPdfDecay = {parameters["history_decay"]!r}f;\n')
        math = VMF.read_text(encoding='utf8') + '\n' + (HERE / 'pdf_pt_direction.h').read_text(encoding='utf8')
        audit = profile != 'normal'
        marker = 'struct PathReservoir\n{'
        fields = """
    float4 labMoment;        // weighted first-hop sum A.xyz, scalar energy B
    float labCount;          // decayed count of frames with direction evidence
    uint labCamera;          // camera and resolution stamp from initial tracing
"""
        change(name, marker, params + math + '\n' + marker + fields + (
            '    float4 labPair;\n    float4 labInitialAudit;\n' if audit else ''))
        # Falcor writes an empty temporal destination even when every shift fails.
        # Initialize the extra payload before any whole-struct UAV store.
        clear_fields = ('this.labMoment = 0.f; this.labCount = 0.f; this.labCamera = 0u;'
                        + (' this.labPair = 0.f; this.labInitialAudit = 0.f;' if audit else ''))
        change(name, 'this.M = 0;\n        this.weight = 0.;',
               clear_fields + '\n        this.M = 0;\n        this.weight = 0.;')
        marker = 'struct PathRISState\n{'
        change(name, marker, marker + """
    float3 labFirstScatter = 0.f;
    float4 labMoment = 0.f;
""" + ('    float4 labInitialAudit = 0.f;\n' if audit else ''))
        # Record *the same local w* summed by native RIS, including rejected lottery candidates.
        marker = '        this.weight += w;\n\n        return (u * this.weight < w);'
        change(name, 'bool addPSSSample(float u, float3 pathContribution)',
               'bool addPSSSample(float u, float3 pathContribution, float3 direction = 0.f, int tag = 0)')
        change(name, marker, """
        float norm2 = dot(direction, direction);
        if (w > 0.f && isfinite(w) && norm2 > 0.f && isfinite(norm2))
        {
            labMoment += float4(direction * rsqrt(norm2), 1.f) * w;
""" + ("""            if (tag == 1) labInitialAudit.x += w;
            if (tag == 2) labInitialAudit.y += w;
            if (tag == 3) labInitialAudit.z += w;
            labInitialAudit.w += w;
""" if audit else '') + '        }\n' + marker)
        # NEE pathLength is vertexIndex-1; BSDF-hit pathLength is vertexIndex-2.
        marker = 'bool selected = addPSSSample(u, pathContribution);'
        start = data[name].index('bool addNEECandidate(')
        end = data[name].index('bool addPrimaryVisibleEmitterCandidate(', start)
        chunk = data[name][start:end]
        if chunk.count(marker) != 2:
            raise ValueError('Initial RIS candidate call graph changed')
        chunk = chunk.replace(marker, 'bool selected = addPSSSample(u, pathContribution, '
                              'labPdfCandidateComponent(pathLength == 0, wi, labFirstScatter), '
                              'pathLength == 0 ? 1 : 2);', 1)
        chunk = chunk.replace(marker, 'bool selected = addPSSSample(u, pathContribution, '
                              'labFirstScatter, 3);')
        # BSDF hits (emissive or environment) use the same already sampled first direction.
        data[name] = data[name][:start] + chunk + data[name][end:]
        data[name] += """
float labPdfPairWeight(PathReservoir a, PathReservoir b)
{
    if (kLabPdfProfile == 1) return 1.f;
    if (kLabPdfProfile == 2 || kLabPdfProfile == 3) return 0.f;
    if (min(a.labMoment.w, b.labMoment.w) <= 0.f) return 1.f;
    float3 av = a.labMoment.xyz / a.labMoment.w;
    float3 bv = b.labMoment.xyz / b.labMoment.w;
    float ar = length(av), br = length(bv);
    float cosine = ar * br > 1e-12f ? dot(av, bv) / (ar * br) : 0.f;
    return labPdfBlend(min(a.labMoment.w, b.labMoment.w), a.labCount, b.labCount,
                       LabPdfSimilarity(ar, br, cosine), kLabPdfHistoryLimit);
}
"""
        name = PT + 'PathTracer.slang'
        marker = 'bool valid = generateScatterRay(sd, mi, path);'
        change(name, marker, marker + """
#if USE_RESTIRPT
        if (valid && isPrimaryHit) path.restirPTData.pathRis.labFirstScatter = path.dir;
#endif""")
        marker = 'restirpt.populateReservoir(path, sampleCount, pixel, params.getReservoirOffset(pixel), params.seed);'
        change(name, marker, marker + """
        // Buffered by ReflectTypes; positions are in tiled reservoir address space.
        uint labOffset = params.getReservoirOffset(pixel);
        restirpt.pathReservoirs[labOffset].labCamera = restirpt.labCameraStamp(params.frameDim);
""")
        name = MODULE + 'ReSTIRPT.slang'
        anchor = '    void populateReservoir('
        change(name, anchor, """
    uint labCameraStampForMatrix(uint2 frameDim, float4x4 viewProjMatNoJitter)
    {
        uint h = (2166136261u ^ frameDim.x) * 16777619u ^ frameDim.y;
        [unroll] for (int r = 0; r < 4; ++r)
            [unroll] for (int c = 0; c < 4; ++c)
                h = (h ^ asuint(viewProjMatNoJitter[r][c])) * 16777619u;
        return h;
    }

    uint labCameraStamp(uint2 frameDim)
    {
        return labCameraStampForMatrix(frameDim, gScene.camera.data.viewProjMatNoJitter);
    }

    uint labPreviousCameraStamp(uint2 frameDim)
    {
        return labCameraStampForMatrix(frameDim, gScene.camera.data.prevViewProjMatNoJitter);
    }

""" + anchor)
        anchor = '        pathReservoirs[reservoirIdx] = pathReservoir;'
        change(name, anchor, """
        pathReservoir.labMoment = path.restirPTData.pathRis.labMoment;
        pathReservoir.labCount = pathReservoir.labMoment.w > 0.f ? 1.f : 0.f;
        pathReservoir.labCamera = 0u;
""" + ('        pathReservoir.labInitialAudit = path.restirPTData.pathRis.labInitialAudit;\n'
       '        pathReservoir.labPair = 0.f;\n' if audit else '') + anchor)
        name = PT + 'GeneratePaths.cs.slang'
        anchor = 'restirpt.pathReservoirs[outIdx].weight = 0;'
        change(name, anchor, 'restirpt.pathReservoirs[outIdx].labMoment = 0.f;\n'
               '            restirpt.pathReservoirs[outIdx].labCount = 0.f;\n            ' + anchor)
        name = MODULE + 'TemporalResampling.cs.slang'
        anchor = '    void execute(const uint2 _pixel)'
        change(name, anchor, (HERE / 'pdf_pt_history.slang').read_text(encoding='utf8') + '\n' + anchor)
        anchor = '        if (!DoPass(pixel))'
        change(name, anchor, '        uint offset = params.getReservoirOffset(pixel);\n'
               '        PathReservoir initial = reservoirs[offset];\n'
               '        labCombineHistory(pixel, initial);\n' + anchor)
        anchor = '            writeTemporalOutputs(pixel, 0.f);\n        }'
        change(name, anchor, anchor + """
        reservoirs[offset].labMoment = initial.labMoment;
        reservoirs[offset].labCount = initial.labCount;
        reservoirs[offset].labCamera = initial.labCamera;
""" + ('        reservoirs[offset].labInitialAudit = initial.labInitialAudit;\n' if audit else ''))
        name = MODULE + 'SpatialResampling.cs.slang'
        anchor = '        reservoirs[centralOffset] = dstReservoir;'
        change(name, anchor, """
        dstReservoir.labMoment = centralReservoir.labMoment;
        dstReservoir.labCount = centralReservoir.labCount;
        dstReservoir.labCamera = centralReservoir.labCamera;
""" + ("""        dstReservoir.labInitialAudit = centralReservoir.labInitialAudit;
        dstReservoir.labPair = float4(neighborValidMask[centralOffset].labPdfH,
            neighborValidMask[centralOffset].labPdfNeighborM, C.c_sum, centralReservoir.M);
""" if audit else '') + anchor)
    return {name: value for name, value in data.items()
            if value != sources[name].replace('\r\n', '\n')}
