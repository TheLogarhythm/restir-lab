#ifndef LAB_TRANSPORT_MATH
#define LAB_TRANSPORT_MATH
// Reflection-direction density of the *visible* GGX normal sampler (Heitz
// 2018, JCGT 7(4), eq.3, followed by the 1/(4 V.H) reflection Jacobian).
// D*G1(V)/(4 N.V), with G1(V)/(N.V) written without a grazing-angle division.
// The sampler is untrimmed; below-horizon draws remain zero-valued attempts.
float LabGgxVndfPdf(float roughness, float3 N, float3 V, float3 L)
{
    float NoV = dot(N, V);
    if (NoV <= 0 || dot(N, L) <= 0) return 0;
    float3 H = normalize(V + L);
    if (dot(V, H) <= 0) return 0;
    float NoH = saturate(dot(N, H));
    float alpha2 = square(square(roughness));
    float D = alpha2 / (M_PI * square(square(NoH) * alpha2 + (1 - square(NoH))));
    return D / (2 * (NoV + sqrt(alpha2 + (1 - alpha2) * square(NoV))));
}
// Inverse of Donut SampleTriangle. Ray-query barycentrics are (b1,b2),
// not the independent uniform random coordinates expected by light sampling.
float2 LabTriangleRandomFromBarycentrics(float2 barycentrics)
{
    float sum = barycentrics.x + barycentrics.y;
    return float2(sum * sum, sum > 0 ? barycentrics.y / sum : 0);
}
#endif
