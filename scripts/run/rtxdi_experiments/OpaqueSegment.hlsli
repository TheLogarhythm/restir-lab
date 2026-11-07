#ifndef LAB_OPAQUE_SEGMENT_HLSLI
#define LAB_OPAQUE_SEGMENT_HLSLI

static const uint LAB_TRACE_CLOSEST_ONLY = 1u;
static const uint LAB_TRACE_SAW_TRANSMISSION = 2u;

// DXR candidates arrive in arbitrary distance order. Find the accepted opaque
// or alpha-tested endpoint first; a zero-transmission sheet is still a layer,
// not an opaque surface at which the path may scatter.
bool LabConsiderOpaqueMaterial(uint instanceIndex, uint geometryIndex, uint triangleIndex,
    float2 barycentrics, inout uint traceFlags)
{
    float3 transmission = 1;
    bool accepted = ConsiderTransparentMaterial(instanceIndex, geometryIndex, triangleIndex,
        barycentrics, transmission);
    if (any(transmission != 1)) traceFlags |= LAB_TRACE_SAW_TRANSMISSION;
    return accepted && any(transmission != 0);
}

RAB_RayPayload LabTraceOpaqueSegment(const RayDesc ray, uint instanceMask)
{
    RAB_RayPayload result = (RAB_RayPayload)0;
    result.instanceID = ~0u;
    result.throughput = 1;
    result.labTraceFlags = LAB_TRACE_CLOSEST_ONLY;
#if USE_RAY_QUERY
    RayQuery<RAY_FLAG_SKIP_PROCEDURAL_PRIMITIVES> closest;
    closest.TraceRayInline(SceneBVH, RAY_FLAG_NONE, instanceMask, ray);
    while (closest.Proceed())
    {
        if (closest.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE &&
            LabConsiderOpaqueMaterial(closest.CandidateInstanceID(), closest.CandidateGeometryIndex(),
                closest.CandidatePrimitiveIndex(), closest.CandidateTriangleBarycentrics(), result.labTraceFlags))
            closest.CommitNonOpaqueTriangleHit();
    }
    if (closest.CommittedStatus() == COMMITTED_TRIANGLE_HIT)
    {
        result.instanceID = closest.CommittedInstanceID();
        result.geometryIndex = closest.CommittedGeometryIndex();
        result.primitiveIndex = closest.CommittedPrimitiveIndex();
        result.barycentrics = closest.CommittedTriangleBarycentrics();
        result.committedRayT = closest.CommittedRayT();
        result.frontFace = closest.CommittedTriangleFrontFace();
    }
#else
    TraceRay(SceneBVH, RAY_FLAG_NONE, instanceMask, 0, 0, 0, ray, result);
#endif

    // Every nonopaque candidate before the final hit must have been enumerated.
    // Opaque/cutout-only segments therefore retain the original one-trace cost.
    if ((result.labTraceFlags & LAB_TRACE_SAW_TRANSMISSION) != 0)
    {
        RayDesc segment = ray;
        if (result.instanceID != ~0u) segment.TMax = result.committedRayT;
        // Keep the original origin/TMin and use the exact endpoint distance;
        // the fixed-endpoint visibility helper's offsets would lose near layers.
        RAB_RayPayload transmission = (RAB_RayPayload)0;
        transmission.instanceID = ~0u;
        transmission.throughput = 1;
#if USE_RAY_QUERY
        RayQuery<RAY_FLAG_SKIP_PROCEDURAL_PRIMITIVES | RAY_FLAG_CULL_OPAQUE> layers;
        layers.TraceRayInline(SceneBVH, RAY_FLAG_NONE, instanceMask, segment);
        while (layers.Proceed())
        {
            if (layers.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE &&
                ConsiderTransparentMaterial(layers.CandidateInstanceID(), layers.CandidateGeometryIndex(),
                    layers.CandidatePrimitiveIndex(), layers.CandidateTriangleBarycentrics(), transmission.throughput))
                layers.CommitNonOpaqueTriangleHit();
        }
#else
        TraceRay(SceneBVH, RAY_FLAG_CULL_OPAQUE, instanceMask, 0, 0, 0, segment, transmission);
#endif
        result.throughput = transmission.throughput;
    }
    result.labTraceFlags = 0;
    return result;
}
#endif
