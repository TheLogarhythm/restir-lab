param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$LaunchPlan,
    [Parameter(Mandatory=$true)][string]$ReferenceWindow,
    [Parameter(Mandatory=$true)][string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
if (-not ('RestirProcessTimes' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class RestirProcessTimes {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool GetProcessTimes(IntPtr handle, out long creation, out long exit, out long kernel, out long user);
}
'@
}
if (-not ('RestirOwnedProcess' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

// Windows 10 JOB_LIST assigns containment atomically during process creation.
// CREATE_SUSPENDED also prevents worker execution until membership is verified.
public sealed class RestirOwnedProcess : IDisposable {
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
        public uint ActiveProcesses;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters {
        public ulong ReadOperations, WriteOperations, OtherOperations;
        public ulong ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct SecurityAttributes {
        public int Length;
        public IntPtr Descriptor;
        public int Inherit;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    struct StartupInfo {
        public int Size;
        public string Reserved, Desktop, Title;
        public uint X, Y, Width, Height, XChars, YChars, Fill, Flags;
        public ushort Show, ReservedBytes;
        public IntPtr ReservedPointer, Input, Output, Error;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct StartupInfoEx {
        public StartupInfo Startup;
        public IntPtr Attributes;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInformation {
        public IntPtr Process, Thread;
        public uint ProcessId, ThreadId;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateJobObjectW(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, uint size);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, uint flags, ref UIntPtr size);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute,
        IntPtr value, UIntPtr size, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll")]
    static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateFileW(string name, uint access, uint sharing, ref SecurityAttributes attributes,
        uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool CreateProcessW(string application, StringBuilder command, IntPtr processAttributes,
        IntPtr threadAttributes, bool inheritHandles, uint flags, IntPtr environment, string directory,
        ref StartupInfoEx startup, out ProcessInformation process);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool member);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool CloseHandle(IntPtr handle);

    IntPtr job, processHandle;
    public Process Worker { get; private set; }
    RestirOwnedProcess(IntPtr ownedJob, IntPtr ownedProcess, Process worker) {
        job = ownedJob; processHandle = ownedProcess; Worker = worker;
    }
    static Win32Exception Error(string operation) {
        return new Win32Exception(Marshal.GetLastWin32Error(), operation);
    }
    static IntPtr OpenStandard(string path, uint access, uint disposition) {
        var security = new SecurityAttributes();
        security.Length = Marshal.SizeOf(typeof(SecurityAttributes));
        security.Inherit = 1;
        IntPtr handle = CreateFileW(path, access, 1, ref security, disposition, 0x80, IntPtr.Zero);
        if (handle == new IntPtr(-1)) throw Error("Open redirected worker handle: " + path);
        return handle;
    }
    public static RestirOwnedProcess Start(string executable, string arguments, string directory,
                                          string stdout, string stderr) {
        IntPtr ownedJob = IntPtr.Zero, attributes = IntPtr.Zero, jobList = IntPtr.Zero;
        IntPtr handleList = IntPtr.Zero, input = IntPtr.Zero, output = IntPtr.Zero, error = IntPtr.Zero;
        bool initialized = false;
        var child = new ProcessInformation();
        Process managed = null;
        try {
            // Null SECURITY_ATTRIBUTES makes the sole job handle non-inheritable.
            ownedJob = CreateJobObjectW(IntPtr.Zero, null);
            if (ownedJob == IntPtr.Zero) throw Error("Create worker ownership job");
            var limits = new ExtendedLimits();
            limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
            if (!SetInformationJobObject(ownedJob, 9, ref limits,
                    (uint)Marshal.SizeOf(typeof(ExtendedLimits)))) throw Error("Set worker job limits");
            input = OpenStandard("NUL", 0x80000000, 3);
            output = OpenStandard(stdout, 0x40000000, 1); // CREATE_NEW: preserve previous logs.
            error = OpenStandard(stderr, 0x40000000, 1);
            UIntPtr size = UIntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 2, 0, ref size);
            if (size == UIntPtr.Zero) throw Error("Size worker attributes");
            attributes = Marshal.AllocHGlobal(checked((int)size.ToUInt64()));
            if (!InitializeProcThreadAttributeList(attributes, 2, 0, ref size))
                throw Error("Initialize worker attributes");
            initialized = true;
            jobList = Marshal.AllocHGlobal(IntPtr.Size);
            Marshal.WriteIntPtr(jobList, ownedJob);
            if (!UpdateProcThreadAttribute(attributes, 0, new IntPtr(0x2000d),
                    jobList, new UIntPtr((uint)IntPtr.Size), IntPtr.Zero, IntPtr.Zero))
                throw Error("Assign atomic worker job attribute");
            // Only the three standard handles are inherited; the job handle never is.
            handleList = Marshal.AllocHGlobal(3 * IntPtr.Size);
            Marshal.WriteIntPtr(handleList, 0, input);
            Marshal.WriteIntPtr(handleList, IntPtr.Size, output);
            Marshal.WriteIntPtr(handleList, 2 * IntPtr.Size, error);
            if (!UpdateProcThreadAttribute(attributes, 0, new IntPtr(0x20002),
                    handleList, new UIntPtr((uint)(3 * IntPtr.Size)), IntPtr.Zero, IntPtr.Zero))
                throw Error("Set worker standard handle allowlist");
            var startup = new StartupInfoEx();
            startup.Startup.Size = Marshal.SizeOf(typeof(StartupInfoEx));
            startup.Startup.Flags = 0x100 | 1; // STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW.
            startup.Startup.Show = 0; // SW_HIDE.
            startup.Startup.Input = input; startup.Startup.Output = output; startup.Startup.Error = error;
            startup.Attributes = attributes;
            // CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED.
            if (!CreateProcessW(executable, new StringBuilder("\"" + executable + "\" " + arguments),
                    IntPtr.Zero, IntPtr.Zero, true, 0x08080004, IntPtr.Zero, directory,
                    ref startup, out child)) throw Error("Create contained suspended worker");
            bool member;
            if (!IsProcessInJob(child.Process, ownedJob, out member)) throw Error("Verify worker ownership");
            if (!member) throw new InvalidOperationException("Worker job membership was not established");
            // Open/cache managed identity before its first instruction, including very short workers.
            managed = Process.GetProcessById((int)child.ProcessId);
            IntPtr retainedManagedHandle = managed.Handle;
            if (ResumeThread(child.Thread) != 1) throw Error("Resume contained worker");
            var result = new RestirOwnedProcess(ownedJob, child.Process, managed);
            ownedJob = IntPtr.Zero; child.Process = IntPtr.Zero; managed = null;
            return result;
        }
        finally {
            // Any failed creation/membership/resume path remains contained and cannot run orphaned.
            if (child.Process != IntPtr.Zero) TerminateProcess(child.Process, 1);
            if (ownedJob != IntPtr.Zero) CloseHandle(ownedJob);
            if (child.Process != IntPtr.Zero) {
                uint waited = WaitForSingleObject(child.Process, 10000);
                CloseHandle(child.Process);
                if (waited != 0) throw new InvalidOperationException("Failed worker launch did not terminate");
            }
            if (child.Thread != IntPtr.Zero) CloseHandle(child.Thread);
            if (managed != null) managed.Dispose();
            if (initialized) DeleteProcThreadAttributeList(attributes);
            if (attributes != IntPtr.Zero) Marshal.FreeHGlobal(attributes);
            if (jobList != IntPtr.Zero) Marshal.FreeHGlobal(jobList);
            if (handleList != IntPtr.Zero) Marshal.FreeHGlobal(handleList);
            if (input != IntPtr.Zero) CloseHandle(input);
            if (output != IntPtr.Zero) CloseHandle(output);
            if (error != IntPtr.Zero) CloseHandle(error);
        }
    }
    public void Dispose() {
        IntPtr ownedJob = Interlocked.Exchange(ref job, IntPtr.Zero);
        if (ownedJob != IntPtr.Zero) CloseHandle(ownedJob);
        IntPtr ownedProcess = Interlocked.Exchange(ref processHandle, IntPtr.Zero);
        if (ownedProcess != IntPtr.Zero) CloseHandle(ownedProcess);
        if (Worker != null) { Worker.Dispose(); Worker = null; }
        GC.SuppressFinalize(this);
    }
    ~RestirOwnedProcess() { Dispose(); }
}
'@
}
$taskUtf8 = New-Object System.Text.UTF8Encoding($false)
$taskRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$taskPlanPath = (Resolve-Path -LiteralPath $LaunchPlan).Path
$taskWindowPath = (Resolve-Path -LiteralPath $ReferenceWindow).Path
$taskPlan = Get-Content -LiteralPath $taskPlanPath -Raw | ConvertFrom-Json
$taskWindow = Get-Content -LiteralPath $taskWindowPath -Raw | ConvertFrom-Json
$taskSuite = (Resolve-Path -LiteralPath $taskPlan.suite_root).Path
if (Test-Path -LiteralPath ($taskPlanPath + '.started.json')) { exit 0 }
$taskStart = [DateTimeOffset]::Parse($taskWindow.not_before_utc)
$taskDeadline = [DateTimeOffset]::Parse($taskWindow.deadline_utc)
if ([DateTimeOffset]::UtcNow -lt $taskStart -or [DateTimeOffset]::UtcNow -ge $taskDeadline) {
    throw 'Outside explicitly approved reference window; no process started.'
}
if ($taskPlan.not_before_utc -ne $taskWindow.not_before_utc -or $taskPlan.deadline_utc -ne $taskWindow.deadline_utc) {
    throw 'Launch plan and approved budget differ.'
}
$taskState = Get-Content -LiteralPath (Join-Path $taskSuite 'state.json') -Raw | ConvertFrom-Json
if ($taskState.evaluation_scope -ne 'sparse-v1' -or $taskState.status -ne 'paused') {
    throw 'Sparse reference preparation is not paused and ready.'
}
$taskExisting = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like 'FullSample*' -or ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'rtxdi_pdf_controlled.py')
})
if ($taskExisting.Count) { throw 'Another renderer or controlled worker is already running.' }
# Python revalidates pinned configuration, sources, disk, all 78 methods and raw
# products, then claims the one-shot plan while holding the OS suite mutex.
$taskLogRoot = Join-Path $taskRoot 'build/pdf-controlled'
$taskLogName = 'sparse-' + [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$taskArguments = '-B scripts/run/rtxdi_pdf_controlled.py --references-only --reference-window "' + $taskWindowPath + '" --launch-plan "' + $taskPlanPath + '"'
$taskOwnership = $null
try {
$taskOwnership = [RestirOwnedProcess]::Start($PythonExecutable, $taskArguments, $taskRoot,
    (Join-Path $taskLogRoot ($taskLogName + '.stdout.log')),
    (Join-Path $taskLogRoot ($taskLogName + '.stderr.log')))
$taskWorker = $taskOwnership.Worker
$taskWorkerHandle = $taskWorker.Handle
$taskWorkerStarted = $taskWorker.StartTime.ToUniversalTime()
$taskProcessJson = @{ pid=$taskWorker.Id; supervisor_pid=$PID; started_utc=[DateTimeOffset]::UtcNow.ToString('o'); stage='scheduled_sparse_references'; stdout=($taskLogName+'.stdout.log'); stderr=($taskLogName+'.stderr.log'); launch_plan=$taskPlanPath; deadline_utc=$taskWindow.deadline_utc; containment='windows_job_kill_on_close'; containment_verified=$true } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $taskLogRoot 'worker-process.json'), $taskProcessJson, $taskUtf8)
while (-not $taskWorker.HasExited) {
    $taskRemainingMilliseconds = ($taskDeadline - [DateTimeOffset]::UtcNow).TotalMilliseconds
    if ($taskRemainingMilliseconds -le 0) { break }
    # Windows PowerShell5.1 Wait-Process caps Timeout at32767seconds. Bounded
    # waits also recompute the fixed wall-clock deadline after clock changes.
    [void]$taskWorker.WaitForExit([int][Math]::Min(60000, [Math]::Ceiling($taskRemainingMilliseconds)))
}
$taskStillRunning = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskWorker.Id)"
$taskForcedStop = $false
if ($taskStillRunning -and $taskStillRunning.CommandLine -match 'rtxdi_pdf_controlled.py' -and [Math]::Abs(($taskStillRunning.CreationDate.ToUniversalTime() - $taskWorkerStarted).TotalSeconds) -lt 1) {
    Stop-Process -Id $taskWorker.Id -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $taskWorker.Id -Timeout 10 -ErrorAction SilentlyContinue
    $taskForcedStop = $true
}
$taskWorker.Refresh()
if (-not $taskWorker.HasExited) { throw 'Owned worker did not exit; deadline stop is unconfirmed.' }
# Redirected Start-Process objects in Windows PowerShell5.1 may not expose
# ExitTime. The retained kernel handle supplies the exact owned-process time.
$taskCreationTime=0L; $taskExitTime=0L; $taskKernelTime=0L; $taskUserTime=0L
if (-not [RestirProcessTimes]::GetProcessTimes($taskWorkerHandle, [ref]$taskCreationTime, [ref]$taskExitTime, [ref]$taskKernelTime, [ref]$taskUserTime) -or $taskExitTime -eq 0) {
    throw 'Owned worker exit timestamp is unavailable.'
}
$taskWorkerExited = [DateTime]::FromFileTimeUtc($taskExitTime)
# Always reap owned renderers, including an orphan from an early Python crash.
# Enumerating after exit closes the late-spawn race; exit time excludes children
# of a later unrelated process that reuses the worker PID.
$taskExpectedRenderer = (Resolve-Path -LiteralPath (Join-Path $taskRoot 'renderers/rtxdi/build/bin/FullSampleReference.exe')).Path
$taskChildren = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ParentProcessId -eq $taskWorker.Id -and $_.Name -like 'FullSample*' -and $_.CreationDate.ToUniversalTime() -ge $taskWorkerStarted.AddSeconds(-1) -and $_.CreationDate.ToUniversalTime() -le $taskWorkerExited
})
foreach ($taskChild in $taskChildren) {
    if ($taskChild.ExecutablePath -ne $taskExpectedRenderer) { throw 'Unexpected owned renderer identity.' }
    Stop-Process -Id $taskChild.ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($taskChild in $taskChildren) { Wait-Process -Id $taskChild.ProcessId -Timeout 10 -ErrorAction SilentlyContinue }
$taskRemainder = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ParentProcessId -eq $taskWorker.Id -and $_.Name -like 'FullSample*' -and $_.CreationDate.ToUniversalTime() -ge $taskWorkerStarted.AddSeconds(-1) -and $_.CreationDate.ToUniversalTime() -le $taskWorkerExited
})
if ($taskRemainder.Count) { throw 'Owned renderer did not exit.' }
if ($taskForcedStop -or $taskChildren.Count) {
    $taskState = Get-Content -LiteralPath (Join-Path $taskSuite 'state.json') -Raw | ConvertFrom-Json
    $taskState.status = if ($taskForcedStop) { 'budget_exhausted' } else { 'failed' }
    $taskState.stage = if ($taskForcedStop) { 'stopped_at_approved_deadline' } else { 'orphan_renderer_stopped' }
    $taskState.worker_pid = $null
    $taskState.updated_utc = [DateTimeOffset]::UtcNow.ToString('o')
    $taskStatePath = Join-Path $taskSuite 'state.json'
    [IO.File]::WriteAllText(($taskStatePath + '.deadline.tmp'), ($taskState | ConvertTo-Json -Depth 100), $taskUtf8)
    Move-Item -LiteralPath ($taskStatePath + '.deadline.tmp') -Destination $taskStatePath -Force
    $taskDeadlineJson = @{ status=$taskState.stage; deadline_utc=$taskWindow.deadline_utc; stopped_pid=$taskWorker.Id; renderer_pids=@($taskChildren.ProcessId); utc=[DateTimeOffset]::UtcNow.ToString('o') } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $taskLogRoot 'sparse-deadline-receipt.json'), $taskDeadlineJson, $taskUtf8)
}
}
finally {
    # A normal script failure closes the same kernel-owned containment as host death.
    if ($null -ne $taskOwnership) { $taskOwnership.Dispose() }
}
