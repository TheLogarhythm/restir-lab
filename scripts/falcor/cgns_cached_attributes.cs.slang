// CGNS reads exactly the shading frame used by the original point selector.
import ResamplingCommon;
import ReSTIRPathTracingParams;
import Scene.ShadingData;
import Scene.Scene;

cbuffer CB
{
    ReSTIRPathTracingParams params;
    Texture2D<PackedHitInfo> vbuffer;
    RWTexture2D<float4> positions;
    RWTexture2D<float4> normals;
};

[numthreads(8, 8, 1)]
void main(uint2 pixel : SV_DispatchThreadID)
{
    if (any(pixel >= params.frameDim)) return;
    HitInfo hit;
    ShadingData sd = getPixelShadingData(params, vbuffer, int2(pixel), hit);
    positions[pixel] = float4(sd.posW, hit.isValid() ? 1.f : 0.f);
    normals[pixel] = float4(sd.frame.N, distance(sd.posW, gScene.camera.data.posW));
}
