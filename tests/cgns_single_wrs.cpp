#include <cmath>
#include <cstdint>
#include <cstdio>
#include "cgns_single_wrs.h"
int main() {
    LabCgnsSingleWrs r=LabCgnsSingleCreate();
    if(r.valid || r.selected != 0xffffffffu || r.weightSum != 0.f) return 1;
    if(LabCgnsSingleInsert(r,1u,-1.f,0.3f) || r.valid || r.weightSum != 0.f) return 2;
    if(!LabCgnsSingleInsert(r,2u,1.f,0.8f) || !r.valid || r.selected!=2u) return 3;
    if(LabCgnsSingleInsert(r,3u,3.f,0.9f) || r.selected!=2u || r.weightSum!=4.f) return 4;
    if(!LabCgnsSingleInsert(r,4u,4.f,0.49f) || r.selected!=4u || r.weightSum!=8.f) return 5;
    if(LabCgnsSingleInsert(r,5u,0.f,0.f) || r.weightSum!=8.f) return 6;
    if(LabCgnsSingleInsert(r,5u,1.f,1.f) || r.weightSum!=8.f) return 7;
    unsigned state=1234567u, selected=0u;
    for(int i=0;i<100000;++i){
        LabCgnsSingleWrs t=LabCgnsSingleCreate();
        LabCgnsSingleInsert(t,0u,1.f,0.f);
        state=1664525u*state+1013904223u;
        float u=float(state >> 8)/16777216.f;
        LabCgnsSingleInsert(t,1u,3.f,u);
        selected += t.selected==1u;
    }
    if(selected < 74200u || selected > 75800u){std::fprintf(stderr,"selected %u\n",selected);return 8;}
    return 0;
}
