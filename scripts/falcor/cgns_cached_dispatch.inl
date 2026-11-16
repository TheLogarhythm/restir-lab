// Private ReSTIRPathTracing member definitions. Included inside namespace Falcor.
void ReSTIRPathTracing::cacheCgnsAttributes(RenderContext* ctx, const ref<Texture>& vbuffer)
{
    FALCOR_PROFILE(ctx, "cgnsCacheAttributes");
    auto root = mpCgnsAttributes->getRootVar();
    mpScene->bindShaderData(root["gScene"]);
    auto cb = root["CB"];
    cb["params"].setBlob(mPathTracerParams);
    cb["vbuffer"] = vbuffer;
    cb["positions"] = mpCgnsPositions;
    cb["normals"] = mpCgnsNormals;
    mpCgnsAttributes->execute(ctx, mFrameDim.x, mFrameDim.y, 1);
}

void ReSTIRPathTracing::selectCgnsNeighbors(RenderContext* ctx, const ref<Texture>& vbuffer, uint32_t round)
{
    FALCOR_PROFILE(ctx, "cgnsSelectNeighbors");
    auto bind = [&](const ref<ComputePass>& pass)
    {
        auto root = pass->getRootVar();
        auto cb = root["CB"];
        cb["params"].setBlob(mPathTracerParams);
        cb["roundId"] = round;
        cb["radius"] = float(mOptions.spatialGatherRadius);
        cb["neighborOffsets"] = mpNeighborOffsets;
        cb["selected"] = mpCgnsNeighbors;
        return cb;
    };
    const bool distinct = mOptions.spatialGatherRadius * mCgnsMinOffsetDistance > 1.25f;
    const auto& selector = distinct ? mpCgnsDistinct : mpCgnsSelect;
    auto cb = bind(selector);
    cb["positions"] = mpCgnsPositions;
    cb["normals"] = mpCgnsNormals;
    selector->execute(ctx, mFrameDim.x, mFrameDim.y, 1);

    if (mpCgnsVerify)
    {
        mpScene->bindShaderData(mpCgnsVerify->getRootVar()["gScene"]);
        auto check = bind(mpCgnsVerify);
        check["vbuffer"] = vbuffer;
        check["counts"] = mpCgnsCounts;
        ctx->clearUAV(mpCgnsCounts->getUAV().get(), uint4(0));
        mpCgnsVerify->execute(ctx, mFrameDim.x, mFrameDim.y, 1);
        auto counts = mpCgnsCounts->getElements<uint32_t>();
        logInfo("CGNS ID check frame={} round={} pixels={} accepted={} mismatches={}",
                mPathTracerParams.frameCount, round, mFrameDim.x * mFrameDim.y, counts[0], counts[1]);
        if (counts[1]) FALCOR_THROW("CGNS selected neighbor differs from the direct V-buffer selector");
    }
}
