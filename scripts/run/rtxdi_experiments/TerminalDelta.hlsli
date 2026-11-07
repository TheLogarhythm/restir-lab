// Complete the secondary mirror lobe with an endpoint-only query. This is a
// deterministic lobe integral, not a sampled lobe: multiply by F, never F/pDelta.
float3 LabSecondaryDeltaEndpoint(RAB_Surface surface)
{
    if (surface.material.roughness >= kMinRoughness || !any(surface.material.specularF0 > 0)) return 0;
    float3 direction = reflect(-surface.viewDir, surface.normal);
    if (dot(direction, surface.geoNormal) <= 0) return 0;
    RayDesc ray = setupContinuationRay(surface.geoNormal, surface.worldPos, direction);
    RAB_RayPayload hit = TraceNextBounce(ray);
    float3 emission = 0;
    if (RAB_IsValidHit(hit))
    {
        if (RAB_RayPayloadIsFrontFace(hit)) emission = RAB_RayPayloadGetEmittedRadiance(hit);
    }
    else if (g_Const.sceneConstants.enableEnvironmentMap)
        emission = RAB_GetEnvironmentRadiance(direction);
    return emission * hit.throughput * Schlick_Fresnel(surface.material.specularF0, saturate(dot(direction, surface.normal)));
}
