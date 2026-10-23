# Configurations

The example describes a proposed configuration shape and is explicitly not runnable. Null fields are unresolved choices, not defaults. Future backend runners must reject incomplete configs and record all effective parameters, including inherited backend defaults.


[pdf-controlled.json](pdf-controlled.json) is the runnable declared matrix for the controlled
PDF campaign. It holds camera/view overrides, frame/capture schedules, ROIs and execution order.
The runner resolves scene registry defaults and freezes the effective conditions and schedule
in each suite. The current values preserve the historical eight-condition, three-seed campaign
and its 78 method runs. Changes require the experiment approvals described in the
[protocol](../protocol.md); this file does not replace budget or reference-policy authorizations.
