    // Reproject initial statistics independently of the sampled light path and its M.
    void labCombineHistory(uint2 pixel, inout PathReservoir sample)
    {
        if (params.frameCount == 0 || kLabPdfDecay == 0.f) return;
        float2 motion = motionVectors[pixel];
        float2 location = floor(float2(pixel) + motion * float2(params.frameDim) + .5f);
        if (!all(isfinite(location)) || any(location < 0.f) || any(location >= float2(params.frameDim))) return;
        int2 previous = int2(location);
        HitInfo hit = HitInfo(vbuffer[pixel]);
        if (!hit.isValid()) return;
        Ray ray = computeRayPredefinedThinLens(pixel, params.frameDim, params.frameCount);
        ShadingData sd = loadShadingData(hit, ray.origin, ray.dir, false);
        HitInfo oldHit;
        ShadingData old = getPixelTemporalShadingData(params, temporalVbuffer, previous, oldHit);
        if (!oldHit.isValid()) return;
        if (hit.getType() != oldHit.getType() || hit.getInstanceID().index != oldHit.getInstanceID().index ||
            hit.getPrimitiveIndex() != oldHit.getPrimitiveIndex() || sd.materialID != old.materialID ||
            sd.frontFacing != old.frontFacing || dot(sd.faceN, old.faceN) < .95f) return;
        float distance = length(sd.posW - gScene.camera.data.posW);
        if (length(sd.posW - old.posW) > .01f * max(.001f, distance)) return;
        PathReservoir prior = prevReservoirs[params.getReservoirOffset(previous)];
        if (prior.labCamera != sample.labCamera || prior.labCount <= 0.f || prior.labMoment.w <= 0.f ||
            !all(isfinite(prior.labMoment)) || !isfinite(prior.labCount)) return;
        float4 total = labPdfSum(sample.labMoment, prior.labMoment, kLabPdfDecay);
        if (!all(isfinite(total))) return;
        sample.labCount = labPdfCount(sample.labCount, prior.labCount, kLabPdfDecay, kLabPdfHistoryLimit);
        sample.labMoment = total;
    }
