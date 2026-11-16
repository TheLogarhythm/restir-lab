"""Private single-neighbor Falcor PT PDF effective-confidence integration.

Tokuyoshi 2023 Algorithm 2 reduces the neighbor confidence before resampling.
GRIS Section 6.2 treats M as confidence and applies it to *both* sides of MIS.
The upstream Falcor spatial merge is already weighted pairwise GRIS: changing
the cached cSum and the local neighbor M therefore carries the same h*M into
canonical reverse MIS, forward shift/MIS, and output reservoir confidence.
The contribution weight is finalized by the native pHat division, without an
additional M division or h multiplication.

The caller supplies labPdfPairWeight(center, neighbor), kLabPdfProfile, and the
direction-history fields through its isolated PathReservoir shader overlay.
Supported only with point reservoirs, one unpaired neighbor, compact retrace,
and no DoF shift; the host must reject unsupported settings. No files are
written by apply(), and no baseline/upstream source is modified.
"""
from pathlib import Path

MARKER = "LAB_PDF_PT_EFFECTIVE_M_V1"
CORE = Path(__file__).with_suffix(".h")
FILES = ("PathReservoir.slang", "GenerateRetraceWorkload.cs.slang", "SpatialResampling.cs.slang", "Shift.slang")


def _replace(text, before, after, name):
    if text.count(before) != 1:
        raise ValueError("Unexpected PDF PT shader anchor in " + name + ": " + before.splitlines()[0])
    return text.replace(before, after, 1)


def apply(files):
    """Return a new filename-to-shader mapping; preserve all unrelated entries.

    Input newlines are preserved. The reflected NeighborValidMask gets two
    floats: labPdfH (finite/clamped applied h) and labPdfNeighborM (h*rawMi).
    They are zeroed per pixel before geometry checks and published once by
    workload generation. Resampling consumes the cached M without reapplying h.
    """
    if not isinstance(files, dict) or not set(FILES).issubset(files):
        raise ValueError("PDF PT MIS requires PathReservoir, workload and spatial sources")
    if any(not isinstance(text, str) for text in files.values()):
        raise ValueError("PDF PT shader sources must be text")
    if any(MARKER in text for text in files.values()):
        raise ValueError("PDF PT MIS overlay already applied")
    result = dict(files)
    newlines = {name: "\r\n" if "\r\n" in files[name] else "\n" for name in FILES}
    source = {name: files[name].replace("\r\n", "\n") for name in FILES}

    name = "PathReservoir.slang"
    text = source[name]
    anchor = "struct NeighborValidMask\n{\n    uint data;\n    float cSum;"
    fields = ("// " + MARKER + "\n" + CORE.read_text(encoding="utf8").rstrip() + "\n\n" + anchor +
              "\n    float labPdfNeighborM; // Applied h * input neighbor M, one-neighbor contract.\n"
              "    float labPdfH; // Applied finite h; validity remains in data bit zero.")
    source[name] = _replace(text, anchor, fields, name)

    name = "GenerateRetraceWorkload.cs.slang"
    text = source[name]
    anchor = "float cSum = centralReservoir.M;"
    text = _replace(text, anchor, anchor + "\n\n"
        "                    // " + MARKER + ": overwrite stale diagnostics for every spatial pixel.\n"
        "                    neighborValidMask[centralOffset].labPdfH = 0.f;\n"
        "                    neighborValidMask[centralOffset].labPdfNeighborM = 0.f;", name)
    anchor = ("neighborValidMask[centralOffset].setValid(i, true);\n\n"
              "                        cSum += neighborReservoir.M;")
    accept = """// LAB_PDF_PT_EFFECTIVE_M_ACCEPT
                        // Compute h exactly once after the native geometry checks.
                        float labPdfH = kLabPdfProfile == 3 ? 0.f : labPdfPairWeight(centralReservoir, neighborReservoir);
                        float labPdfMi = labPdfEffectiveNeighborM(neighborReservoir.M, labPdfH);
                        neighborValidMask[centralOffset].labPdfH =
                            (isnan(labPdfH) || isinf(labPdfH)) ? 0.f : min(1.f, max(0.f, labPdfH));
                        neighborValidMask[centralOffset].labPdfNeighborM = labPdfMi;
                        if (labPdfMi <= 0.f)
                        {
                            neighborValidMask[centralOffset].setValid(i, false);
                            continue;
                        }
                        neighborValidMask[centralOffset].setValid(i, true);
                        cSum += labPdfMi;

                        """.rstrip()
    source[name] = _replace(text, anchor, accept, name)

    name = "SpatialResampling.cs.slang"
    text = source[name]
    anchor = "int neighborCount = getNeighborCount();"
    text = _replace(text, anchor, "// " + MARKER + ": independent center-only oracle.\n"
        "        // It uses only native central merge/finalize and never reads h/M/mask.\n"
        "        int neighborCount = kLabPdfProfile == 3 ? 0 : getNeighborCount();", name)
    anchor = ("PairwiseFactor C = { neighborValidMask[centralOffset].cSum, centralReservoir.M };\n"
              "        float canonicalWeight = C.c_c / C.c_sum;")
    text = _replace(text, anchor,
        "PairwiseFactor C = { centralReservoir.M, centralReservoir.M };\n"
        "        float canonicalWeight = 1.f;\n"
        "        if (kLabPdfProfile != 3)\n"
        "        {\n"
        "            C.c_sum = neighborValidMask[centralOffset].cSum;\n"
        "            canonicalWeight = C.c_sum > 0.f ? C.c_c / C.c_sum : 0.f;\n"
        "        }", name)
    anchor = "PathReservoir neighborReservoir = prevReservoirs[neighborOffset];"
    text = _replace(text, anchor, anchor + "\n\n"
        "            // " + MARKER + ": both MIS directions and native merge consume h*Mi.\n"
        "            // Do not change the source contribution weight or multiply h again.\n"
        "            neighborReservoir.M = neighborValidMask[centralOffset].labPdfNeighborM;\n"
        "            if (neighborReservoir.M <= 0.f) continue;", name)
    # With one neighbor Mi equals Csum-Mc algebraically. Subtracting Mc
    # can erase a small fractional Mi, so use the cached mass on both sides.
    anchor = "canonicalAtOtherPHat * (C.c_sum - C.c_c)"
    if text.count(anchor) != 2:
        raise ValueError("Unexpected spatial reverse MIS")
    source[name] = text.replace(anchor, "canonicalAtOtherPHat * neighborReservoir.M")

    name = "Shift.slang"
    # Only the unpaired forward shift is active. Preserve native arithmetic
    # order for positive targets and keep the Jacobian in its original place.
    anchor = ("float srcTerm = PathRISState::toScalar(srcReservoir.integrand) * (C.c_sum - C.c_c);\n"
              "    float misWeight = srcReservoir.M / C.c_sum * srcTerm / "
              "(srcTerm + Jacobian * PathRISState::toScalar(dstIntegrand) * C.c_c);")
    start = source[name].index("bool shiftAndMergeReservoirSpatial(")
    end = source[name].index("bool shiftAndMergeReservoirSpatialWithPrecomputedInfo(", start)
    method = _replace(source[name][start:end], anchor,
        "float srcTerm = PathRISState::toScalar(srcReservoir.integrand) * srcReservoir.M;\n"
        "    float denom = srcTerm + Jacobian * PathRISState::toScalar(dstIntegrand) * C.c_c;\n"
        "    float misWeight = denom > 0.f ? srcReservoir.M / C.c_sum * srcTerm / denom : 0.f;", name)
    source[name] = source[name][:start] + method + source[name][end:]
    for name in FILES:
        result[name] = source[name].replace("\n", newlines[name])
    return result
