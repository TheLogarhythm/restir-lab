// The production HLSL/C++ header is the implementation under test.
#include <cmath>
#include <cassert>
#include <limits>
#include <random>
#include "CgnsMath.h"

bool near(float a, float b, float tolerance = 1e-5f) { return std::abs(a-b) < tolerance; }

void score_and_scale()
{
    assert(near(LabCgnsScale(10.f, .05f), 1.26156626f));
    assert(near(LabCgnsScore(0.f, 1.f, 10.f, .05f, 8.f), 1.f));
    assert(near(LabCgnsScore(1.26156626f, 1.f, 10.f, .05f, 8.f), .36787944f));
    assert(near(LabCgnsScore(0.f, .5f, 10.f, .05f, 8.f), .00390625f));
    assert(LabCgnsScore(0.f, -1.f, 10.f, .05f, 8.f) == 0.f);
    // Geometrically scaling the scene must preserve compatibility.
    assert(near(LabCgnsScore(1.f, .9f, 10.f, .05f, 8.f),
                LabCgnsScore(100.f, .9f, 1000.f, .05f, 8.f)));
    assert(LabCgnsScore(1.f, 1.f, 0.f, .05f, 8.f) == 0.f);
    assert(LabCgnsScore(1.f, 1.f, 1.f, 0.f, 8.f) == 0.f);
    assert(LabCgnsScore(std::numeric_limits<float>::infinity(), 1.f, 1.f, .05f, 8.f) == 0.f);
    assert(LabCgnsScore(1.f, std::numeric_limits<float>::quiet_NaN(), 1.f, .05f, 8.f) == 0.f);
}

void single_neighbor_probabilities()
{
    // One million evenly spaced draws give exact 1:3 selection frequencies.
    unsigned second = 0;
    for (unsigned i = 0; i < 1000000; ++i)
    {
        auto r = LabCgnsCreateReservoir();
        LabCgnsInsert(r, 10, 1.f, .25f, 1);
        LabCgnsInsert(r, 20, 3.f, (i + .5f)/1000000.f, 1);
        assert(r.count == 1);
        second += r.pixels[0] == 20;
    }
    assert(second == 750000);
}

void multiple_neighbors()
{
    auto r = LabCgnsCreateReservoir();
    // Equal random draws: the final set is the three largest weights.
    for (unsigned i = 1; i <= 6; ++i) LabCgnsInsert(r, i, float(i), .5f, 3);
    assert(r.count == 3);
    unsigned mask = 0;
    for (unsigned i = 0; i < r.count; ++i) mask |= 1u << r.pixels[i];
    assert(mask == ((1u << 4) | (1u << 5) | (1u << 6)));
    // A repeated retained pixel must not consume a second slot.
    LabCgnsInsert(r, r.pixels[0], 100.f, .999f, 3);
    for (unsigned i = 0; i < r.count; ++i)
        for (unsigned j = 0; j < i; ++j) assert(r.pixels[i] != r.pixels[j]);

    // Equal weights must produce symmetric inclusion probabilities.
    std::mt19937 generator(6132);
    std::uniform_real_distribution<float> uniform(0.f, 1.f);
    unsigned included[4] = {};
    for (unsigned trial = 0; trial < 100000; ++trial)
    {
        r = LabCgnsCreateReservoir();
        for (unsigned pixel = 0; pixel < 4; ++pixel) LabCgnsInsert(r, pixel, 1.f, uniform(generator), 2);
        assert(r.count == 2);
        assert(r.pixels[0] != r.pixels[1]);
        for (unsigned i = 0; i < 2; ++i) ++included[r.pixels[i]];
    }
    for (auto count : included) assert(count > 49000 && count < 51000);
}

void tiny_weights_preserve_order_and_common_scaling()
{
    // Equal draws must retain the two largest weights, even near FLT_MIN.
    // Direct log(u)/weight overflows for all three unscaled priorities.
    const float weights[] = {1.2e-38f, 1.4e-38f, 1.6e-38f};
    for (float scale : {1.f, 1e20f, 1e37f})
    {
        auto r = LabCgnsCreateReservoir();
        for (unsigned i = 0; i < 3; ++i)
            LabCgnsInsert(r, i + 1, weights[i] * scale, 1.f / 1024.f, 2);
        assert(r.count == 2);
        unsigned mask = 0;
        for (unsigned i = 0; i < r.count; ++i)
        {
            assert(std::isfinite(r.keys[i]));
            mask |= 1u << r.pixels[i];
        }
        assert(mask == ((1u << 2) | (1u << 3)));
    }
}

void empty_invalid_and_endpoints()
{
    auto r = LabCgnsCreateReservoir();
    for (auto pixel : r.pixels) assert(pixel == 0xffffffffu);
    assert(r.count == 0);
    assert(!LabCgnsInsert(r, 1, 1.f, .5f, 0));
    assert(!LabCgnsInsert(r, 1, 1.f, .5f, 5));
    assert(!LabCgnsInsert(r, 0xffffffffu, 1.f, .5f, 4));
    assert(!LabCgnsInsert(r, 1, 0.f, .5f, 4));
    assert(!LabCgnsInsert(r, 1, -1.f, .5f, 4));
    assert(!LabCgnsInsert(r, 1, std::numeric_limits<float>::infinity(), .5f, 4));
    assert(!LabCgnsInsert(r, 1, std::numeric_limits<float>::quiet_NaN(), .5f, 4));
    assert(r.count == 0);
    // random=0 is legal for our sampler; logarithms must remain finite.
    assert(LabCgnsInsert(r, 1, 1.f, 0.f, 4));
    assert(LabCgnsInsert(r, 2, 1.f, 1.f, 4));
    assert(std::isfinite(r.keys[0]) && std::isfinite(r.keys[1]));
    assert(r.count == 2);
    assert(r.pixels[2] == 0xffffffffu && r.pixels[3] == 0xffffffffu);
    assert(!LabCgnsInsert(r, 3, 1.f, std::numeric_limits<float>::quiet_NaN(), 4));

    // Zero keeps the existing positive lower clamp.
    r = LabCgnsCreateReservoir();
    LabCgnsInsert(r, 1, 1.f, 0.f, 2);
    LabCgnsInsert(r, 2, 1.f, 1e-8f, 2);
    assert(r.keys[0] == r.keys[1]);

    // u=1 has the highest priority regardless of weight, and ties retain earlier pixels.
    r = LabCgnsCreateReservoir();
    assert(LabCgnsInsert(r, 1, std::numeric_limits<float>::min(), 1.f, 2));
    assert(LabCgnsInsert(r, 2, 1.f, 1.f, 2));
    assert(std::isfinite(r.keys[0]) && r.keys[0] == r.keys[1]);
    assert(!LabCgnsInsert(r, 3, std::numeric_limits<float>::max(), 1.f, 2));
    assert(!LabCgnsInsert(r, 3, std::numeric_limits<float>::max(), std::nextafter(1.f, 0.f), 2));
    assert(r.pixels[0] == 1 && r.pixels[1] == 2);
}

void disk_mapping()
{
    auto center = LabCgnsConcentric(.5f, .5f);
    assert(center.x == 0.f && center.y == 0.f);
    auto right = LabCgnsConcentric(1.f, .5f);
    assert(near(right.x, 1.f) && near(right.y, 0.f));
    double sumX = 0, sumY = 0, sumRadius2 = 0;
    for (unsigned i = 0; i < 8192; ++i)
    {
        auto disk = LabCgnsDiskOffset(i);
        float radius2 = disk.x*disk.x + disk.y*disk.y;
        assert(radius2 <= 1.000001f);
        sumX += disk.x; sumY += disk.y; sumRadius2 += radius2;
        auto wrapped = LabCgnsDiskOffset(i+8192);
        assert(disk.x == wrapped.x && disk.y == wrapped.y);
    }
    assert(std::abs(sumX/8192) < .005 && std::abs(sumY/8192) < .005);
    assert(std::abs(sumRadius2/8192-.5) < .005);
}

int main()
{
    score_and_scale();
    single_neighbor_probabilities();
    multiple_neighbors();
    tiny_weights_preserve_order_and_common_scaling();
    empty_invalid_and_endpoints();
    disk_mapping();
}
