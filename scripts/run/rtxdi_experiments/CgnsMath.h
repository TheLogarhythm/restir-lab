// Independent CGNS implementation: Junkins et al. 2026, Eqs. 14--15 and Algorithm 1.
// Scalar HLSL/C++ subset; tests execute the same scoring and WRS functions as shaders.
#ifndef LAB_CGNS_MATH_H
#define LAB_CGNS_MATH_H
#ifdef __cplusplus
// C++ callers include <cmath>; ShaderMake scans even conditional includes.
using uint = unsigned;
using std::sqrt; using std::exp; using std::pow; using std::log;
using std::floor; using std::cos; using std::sin; using std::abs; using std::isfinite;
#define LAB_CGNS_INLINE inline
#define LAB_CGNS_INOUT(type) type&
#else
#define LAB_CGNS_INLINE
#define LAB_CGNS_INOUT(type) inout type
#endif

static const uint LAB_CGNS_MAX_NEIGHBORS = 4u;
static const uint LAB_CGNS_DISK_SAMPLES = 8192u;
static const uint LAB_CGNS_INVALID_PIXEL = 0xffffffffu;

LAB_CGNS_INLINE float LabCgnsScale(float cameraDistance, float solidAngle)
{
    if (!isfinite(cameraDistance) || !isfinite(solidAngle) || cameraDistance <= 0.f || solidAngle <= 0.f)
        return 0.f;
    return cameraDistance * sqrt(solidAngle / 3.14159265358979323846f);
}

LAB_CGNS_INLINE float LabCgnsScore(float worldDistance, float normalCosine,
    float cameraDistance, float solidAngle, float normalBeta)
{
    float scale = LabCgnsScale(cameraDistance, solidAngle);
    if (!isfinite(scale) || scale <= 0.f || !isfinite(worldDistance) || worldDistance < 0.f
        || !isfinite(normalCosine) || !isfinite(normalBeta) || normalBeta < 0.f)
        return 0.f;
    float cosine = normalCosine < 0.f ? 0.f : (normalCosine > 1.f ? 1.f : normalCosine);
    return exp(-worldDistance / scale) * (normalBeta == 0.f ? 1.f : pow(cosine, normalBeta));
}

struct LabCgnsOffset { float x; float y; };

LAB_CGNS_INLINE LabCgnsOffset LabCgnsConcentric(float u, float v)
{
    float a = 2.f*u-1.f, b = 2.f*v-1.f;
    LabCgnsOffset result;
    result.x = result.y = 0.f;
    if (a == 0.f && b == 0.f) return result;
    float radius, angle;
    if (abs(a) > abs(b))
    {
        radius = a;
        angle = .7853981633974483f * (b/a);
    }
    else
    {
        radius = b;
        angle = 1.570796326794897f - .7853981633974483f * (a/b);
    }
    result.x = radius*cos(angle);
    result.y = radius*sin(angle);
    return result;
}

LAB_CGNS_INLINE LabCgnsOffset LabCgnsDiskOffset(uint index)
{
    float n = float(index % LAB_CGNS_DISK_SAMPLES + 1u);
    float u = .5f + n*.7548776662466927f;
    float v = .5f + n*.5698402909980532f;
    return LabCgnsConcentric(u-floor(u), v-floor(v));
}

struct LabCgnsReservoir
{
    uint pixels[LAB_CGNS_MAX_NEIGHBORS];
    float keys[LAB_CGNS_MAX_NEIGHBORS];
    float weightSum;
    uint count;
};

LAB_CGNS_INLINE LabCgnsReservoir LabCgnsCreateReservoir()
{
    LabCgnsReservoir result;
    result.weightSum = 0.f;
    result.count = 0u;
    for (uint i = 0u; i < LAB_CGNS_MAX_NEIGHBORS; ++i)
    {
        result.pixels[i] = LAB_CGNS_INVALID_PIXEL;
        result.keys[i] = -3.402823466e38f;
    }
    return result;
}

// Feed distinct candidate pixels with a fixed capacity. The caller deduplicates
// the input stream after raster rounding; this guard also prevents repeated output slots.
LAB_CGNS_INLINE bool LabCgnsInsert(LAB_CGNS_INOUT(LabCgnsReservoir) reservoir,
    uint pixel, float weight, float random, uint capacity)
{
    if (capacity == 0u || capacity > LAB_CGNS_MAX_NEIGHBORS || pixel == LAB_CGNS_INVALID_PIXEL
        || !isfinite(weight) || weight <= 0.f || !isfinite(random) || random < 0.f || random > 1.f)
        return false;
    for (uint i = 0u; i < reservoir.count; ++i)
        if (reservoir.pixels[i] == pixel) return false;

    if (capacity == 1u)
    {
        // A-Chao: retain one candidate proportionally to its weight.
        reservoir.weightSum += weight;
        if (reservoir.count == 0u || random < weight/reservoir.weightSum)
        {
            reservoir.pixels[0] = pixel;
            reservoir.count = 1u;
            return true;
        }
        return false;
    }

    // A-ES: log(weight)-log(-log(u)) preserves the ordering of log(u)/weight
    // without overflowing when a positive compatibility score is very small.
    // u=1 remains the highest priority, with equal keys retaining earlier pixels.
    float key = 3.402823466e38f;
    if (random < 1.f)
        key = log(weight) - log(-log(random > 1e-8f ? random : 1e-8f));
    uint slot = reservoir.count;
    if (slot == capacity)
    {
        slot = 0u;
        for (uint i = 1u; i < capacity; ++i)
            if (reservoir.keys[i] < reservoir.keys[slot]) slot = i;
        if (key <= reservoir.keys[slot]) return false;
    }
    else ++reservoir.count;
    reservoir.pixels[slot] = pixel;
    reservoir.keys[slot] = key;
    return true;
}

#undef LAB_CGNS_INLINE
#undef LAB_CGNS_INOUT
#endif
