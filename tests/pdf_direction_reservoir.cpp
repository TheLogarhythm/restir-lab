#include <cmath>
#include <cassert>
#include <initializer_list>
#include "PdfReservoirMath.h"

static void near(float actual, float expected) { assert(std::abs(actual - expected) < 1e-6f); }

int main()
{
    static_assert(sizeof(LabDirectionReservoir) == 32, "GPU buffer layout changed");
    LabDirectionReservoir fresh = {0x80000001u, 11, 1.5f, 1.f, {1, 0, 0}, 0};
    LabDirectionReservoir old = {0x80000002u, 22, .5f, 4.f, {0, 1, 0}, 0};
    // Eqs. 17--18: w_fresh=4/3, w_history=15/16, sum=109/48.
    for (float random : {0.f, .9f}) {
        auto r = LabMergeDirection(fresh, old, 2.f, 1.f, 3.f, 2.f, 2.5f, random);
        bool history = random == 0.f;
        assert(r.lightData == (history ? old.lightData : fresh.lightData));
        assert(r.uvData == (history ? old.uvData : fresh.uvData));
        near(r.M, 3.5f);
        near(r.W, history ? 109.f / 144.f : 109.f / 96.f);
        near(r.moment.x, 64.f / 109.f);
        near(r.moment.y, 45.f / 109.f);
        near(r.moment.z, 0.f);
    }
    // Rejected/zero-weight history cannot alter fresh state or its candidate count.
    for (int field = 0; field < 3; ++field) {
        auto invalid = old;
        if (field == 0) invalid.W = 0;
        if (field == 1) invalid.M = 0;
        if (field == 2) invalid.lightData = 0;
        auto r = LabMergeDirection(fresh, invalid, 2, 1, 3, 2, 2.5f, 0);
        assert(r.lightData == fresh.lightData && r.uvData == fresh.uvData);
        near(r.W, fresh.W); near(r.M, 1); near(r.moment.x, 1); near(r.moment.y, 0);
    }
    auto empty = fresh;
    empty.W = 0; empty.moment = {0, 0, 0};
    auto r = LabMergeDirection(empty, old, 0, 0, 3, 2, 2.5f, 0);
    assert(r.lightData == old.lightData);
    near(r.W, 5.f / 16.f); near(r.M, 3.5f); near(r.moment.y, 1);
    r = LabMergeDirection(empty, old, 0, 0, 0, 0, 2.5f, 0);
    near(r.W, 0); near(r.M, 3.5f);
    near(r.moment.x, 0); near(r.moment.y, 0); near(r.moment.z, 0);
    r = LabMergeDirection(fresh, old, 2, 1, 3, 2, 0, 0);
    near(r.W, fresh.W); near(r.M, 1); near(r.moment.x, 1);
}
