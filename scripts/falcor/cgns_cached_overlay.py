"""Build the cached point-CGNS shaders and minimal changes to the private PT host."""
from pathlib import Path

from . import cgns_single_overlay as original

HERE = Path(__file__).resolve().parent
MODULE = original.MODULE
CONSUMERS = {name: count for name, count in original.FILES.items() if count}
STAGES = ('attributes', 'select', 'verify')
HOST_IMPLEMENTATION = HERE / 'cgns_cached_dispatch.inl'


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Unexpected pinned Falcor or selector source near ' + old[:80])
    return text.replace(old, new)


def selector(parameters, *, cached):
    source = original.parameterize_selector(parameters)
    if cached:
        source = replace(source, 'Texture2D<PackedHitInfo> vbuffer',
                         'Texture2D<float4> positions, Texture2D<float4> normals')
        source = replace(source, """HitInfo centerHit;
    ShadingData center=getPixelShadingData(params, vbuffer, int2(pixel), centerHit);
    if (!centerHit.isValid()) return result;""", """float4 center = positions[pixel];
    if (center.w == 0.f) return result;
    float3 centerNormal = normals[pixel].xyz;""")
        source = replace(source, """HitInfo candidateHit;
        ShadingData neighbor=getPixelShadingData(params,vbuffer,candidate,candidateHit);
        if (!candidateHit.isValid()) continue;""", """float4 neighbor = positions[candidate];
        if (neighbor.w == 0.f) continue;""")
        source = replace(source, 'center.posW', 'center.xyz', 2)
        source = replace(source, 'neighbor.posW', 'neighbor.xyz')
        source = replace(source, 'center.frame.N,neighbor.frame.N', 'centerNormal,normals[candidate].xyz')
        source = replace(source, 'distance(center.xyz, gScene.camera.data.posW)', 'normals[pixel].w')
        source = replace(source, '!isValidScreenRegion(params,candidate)', 'any(candidate < 0) || any(candidate >= int2(params.frameDim))')
        # Specialize the same WRS loop. A candidate handle is opaque to WRS,
        # so it can store the accepted linear pixel ID instead of a list index.
        fn = source[source.index('LabCgnsPointSelection labCgnsSelectPointNeighbors('):]
        fn = replace(fn, 'labCgnsSelectPointNeighbors(', 'labCgnsDistinctNeighbors(')
        fn = replace(fn, '    int2 seen[LAB_CGNS_CANDIDATE_COUNT];\n    uint seenCount=0;\n', '')
        start, end = fn.index('        bool duplicate=false;'), fn.index('        float4 neighbor =')
        fn = fn[:start] + '        uint candidateIndex = uint(candidate.y) * params.frameDim.x + uint(candidate.x);\n' + fn[end:]
        fn = replace(fn, 'seen[reservoir.selected]', 'int2(reservoir.selected % params.frameDim.x, reservoir.selected / params.frameDim.x)')
        source += '\n' + fn
    return original.CORE.read_text(encoding='utf8') + '\n' + source


def shader_outputs(runtime, parameters):
    outputs = {}
    for name, count in CONSUMERS.items():
        rel = (MODULE / name).as_posix()
        source = (runtime / rel).read_text(encoding='utf8')
        source = replace(source, 'Texture1D<float2> neighborOffsets;',
                         'Texture1D<float2> neighborOffsets;\n    Texture2D<uint> cgnsNeighbors;')
        for index in ('i', 'retraceIndex / 2'):
            before = f'getNextNeighborPixel(startIndex, neighborOffsets, pixel, {index}, spatialRadius)'
            if before in source:
                source = replace(source, before, 'decodeCgnsNeighbor(cgnsNeighbors[pixel], params.frameDim.x)')
        if source.count('decodeCgnsNeighbor(') != count or 'getNextNeighborPixel(' in source:
            raise ValueError('Unexpected neighbor lookup in ' + name)
        outputs[rel] = source
    common = (MODULE / 'ResamplingCommon.slang').as_posix()
    outputs[common] = (runtime / common).read_text(encoding='utf8') + """
int2 decodeCgnsNeighbor(uint id, uint width)
{
    if (id == 0xffffffffu) return int2(-1, -1);
    return int2(id % width, id / width);
}
"""
    for stage in STAGES:
        name = 'cgns_cached_' + stage + '.cs.slang'
        source = (HERE / name).read_text(encoding='utf8')
        if stage != 'attributes':
            source = replace(source, '__LAB_SELECTOR__', selector(parameters, cached=stage == 'select'))
        outputs[(MODULE / name).as_posix()] = source
    return outputs


def host_sources(module):
    header = (module / 'ReSTIRPathTracing.h').read_text(encoding='utf8')
    header = replace(header, '        ref<ComputePass> mpSpatialResampling;', """
        void cacheCgnsAttributes(RenderContext* ctx, const ref<Texture>& vbuffer);
        void selectCgnsNeighbors(RenderContext* ctx, const ref<Texture>& vbuffer, uint32_t round);
        ref<ComputePass> mpCgnsAttributes, mpCgnsSelect, mpCgnsDistinct, mpCgnsVerify;
        ref<Texture> mpCgnsPositions, mpCgnsNormals, mpCgnsNeighbors;
        ref<Buffer> mpCgnsCounts;
        float mCgnsMinOffsetDistance = 0.f;
        ref<ComputePass> mpSpatialResampling;""")
    cpp = (module / 'ReSTIRPathTracing.cpp').read_text(encoding='utf8')
    cpp = replace(cpp, '#include <array>', '#include <array>\n#include <cstdlib>')
    anchor = '        return mpDevice->createTexture1D(sampleCount, ResourceFormat::RG8Snorm'
    cpp = replace(cpp, anchor, """        // Lower bound over all circular windows of up to 32 candidates.
        // Rounding two positions to the same pixel requires distance <= 1
        // on both axes. Leave 0.25 pixel of margin for FP32 addition/rounding.
        int minDistance = 255;
        for (uint32_t i = 0; i < sampleCount; ++i)
            for (uint32_t k = 1; k < 32; ++k)
            {
                uint32_t j = (i + k) % sampleCount;
                int dx = std::abs(int(offsets[2*i]) - int(offsets[2*j]));
                int dy = std::abs(int(offsets[2*i+1]) - int(offsets[2*j+1]));
                minDistance = std::min(minDistance, std::max(dx, dy));
            }
        mCgnsMinOffsetDistance = float(minDistance) / 127.f;
""" + anchor)
    anchor = '        prepareVBufferTextures(frameDim);'
    cpp = replace(cpp, anchor, anchor + """
        const bool spatial = mOptions.useSpatialResampling;
        createTexture2D(mpCgnsPositions, frameDim.x, frameDim.y, ResourceFormat::RGBA32Float, spatial);
        createTexture2D(mpCgnsNormals, frameDim.x, frameDim.y, ResourceFormat::RGBA32Float, spatial);
        createTexture2D(mpCgnsNeighbors, frameDim.x, frameDim.y, ResourceFormat::R32Uint, spatial);
""")
    anchor = '        createComputePass(mpSpatialRetrace, kSpatialRetraceFile, defines, baseDesc);'
    cpp = replace(cpp, anchor, """        if (mOptions.useAreaReservoirs || mOptions.usePairedNeighbors ||
            mOptions.spatialNeighborCount != 1 || !useCompactRetraceSchedule())
            FALCOR_THROW("Cached CGNS requires point reservoirs, one unpaired neighbor and compact retrace");
        createComputePass(mpCgnsAttributes, "ReSTIRPathTracing/cgns_cached_attributes.cs.slang", defines, baseDesc);
        createComputePass(mpCgnsSelect, "ReSTIRPathTracing/cgns_cached_select.cs.slang", defines, baseDesc);
        createComputePass(mpCgnsDistinct, "ReSTIRPathTracing/cgns_cached_select.cs.slang", defines, baseDesc, "selectDistinct");
        const char* verify = std::getenv("RESTIR_LAB_CGNS_VERIFY_IDS");
        if (verify && std::string(verify) == "1")
        {
            createComputePass(mpCgnsVerify, "ReSTIRPathTracing/cgns_cached_verify.cs.slang", defines, baseDesc);
            createOrDestroyRawBuffer(mpCgnsCounts, 2 * sizeof(uint32_t));
        }
""" + anchor)
    anchor = '    void ReSTIRPathTracing::spatialResampling(RenderContext*'
    cpp = replace(cpp, anchor, HOST_IMPLEMENTATION.read_text(encoding='utf8') + '\n' + anchor)
    for var, after in [('var', 'ShaderVar var = bindSpatialResamplingVars'),
                       ('retraceVar', 'ShaderVar retraceVar = bindSpatialResamplingVars'),
                       ('workLoadVar', 'workLoadVar = bindSpatialResamplingVars')]:
        line, = [line for line in cpp.splitlines() if after in line]
        cpp = replace(cpp, line, line + '\n' + ' ' * (len(line) - len(line.lstrip()))
                      + var + '["cgnsNeighbors"] = mpCgnsNeighbors;')
    anchor = '        for (uint32_t iteration = 0; iteration < mOptions.spatialIterations; ++iteration)'
    cpp = replace(cpp, anchor, '        if (mOptions.spatialIterations) cacheCgnsAttributes(pRenderContext, pVBuffer);\n' + anchor)
    anchor = '            std::swap(mpReservoirs, mpPrevReservoirs);'
    cpp = replace(cpp, anchor, anchor + '\n            selectCgnsNeighbors(pRenderContext, pVBuffer, iteration);')
    return {'ReSTIRPathTracing.h': header, 'ReSTIRPathTracing.cpp': cpp}
