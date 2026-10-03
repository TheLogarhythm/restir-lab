#include <cassert>
#include "PdfViewerState.h"
int main()
{
    PdfViewerState viewer;
    assert(viewer.enabled && viewer.frame == 0);
    viewer.Advance();
    viewer.Update(false, false);
    assert(!viewer.enabled && viewer.frame == 0);
    viewer.Advance();
    viewer.Update(false, false); // An unchanged checkbox must preserve history.
    assert(!viewer.enabled && viewer.frame == 1);
    viewer.Update(true, false);
    assert(viewer.enabled && viewer.frame == 0);
    viewer.Advance();
    viewer.Update(true, true);
    assert(viewer.enabled && viewer.frame == 0);
    viewer.Advance();
    viewer.Update(true, false);
    assert(viewer.frame == 1);
    assert(PdfViewerState::Supported(true, true, true, true, false));
    assert(!PdfViewerState::Supported(false, true, true, true, false));
    assert(!PdfViewerState::Supported(true, false, true, true, false));
    assert(!PdfViewerState::Supported(true, true, false, true, false));
    assert(!PdfViewerState::Supported(true, true, true, false, false));
    assert(!PdfViewerState::Supported(true, true, true, true, true));
    // Changing to an incompatible renderer disables PDF and clears its history.
    viewer.Update(true, false, false);
    assert(!viewer.enabled && viewer.frame == 0);
    viewer.Advance();
    viewer.Update(true, false, false);
    assert(!viewer.enabled && viewer.frame == 1);
    // The user's preference can be restored when returning to supported DI.
    viewer.Update(true, false, true);
    assert(viewer.enabled && viewer.frame == 0);
}
