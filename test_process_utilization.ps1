param (
    [int]$SampleSeconds = 5,
    [int]$TopN = 15
)

Write-Host "=== Process Utilization Test Script ===" -ForegroundColor Cyan
Write-Host "Sample Period: $SampleSeconds seconds"
Write-Host "Top Processes: $TopN"
Write-Host ""

# Step 1: First snapshot
Write-Host "Taking first snapshot..." -ForegroundColor Yellow
$proc1 = Get-Process | Select-Object Id, Name, CPU, WorkingSet64

Start-Sleep -Seconds $SampleSeconds

# Step 2: Second snapshot
Write-Host "Taking second snapshot..." -ForegroundColor Yellow
$proc2 = Get-Process | Select-Object Id, Name, CPU, WorkingSet64

# Step 3: System resource details
$cpuCount = (Get-WmiObject Win32_ComputerSystem).NumberOfLogicalProcessors
$totalMem = (Get-WmiObject Win32_OperatingSystem).TotalVisibleMemorySize * 1KB

Write-Host "System Info:" -ForegroundColor Green
Write-Host "  CPU Cores: $cpuCount"
Write-Host "  Total Memory: $([math]::Round($totalMem / 1GB, 2)) GB"
Write-Host ""

# Step 4: Compute CPU & Memory%
$result = foreach ($p2 in $proc2) {
    $p1 = $proc1 | Where-Object { $_.Id -eq $p2.Id }
    if ($p1 -and $p2.CPU -ne $null) {
        $cpuDelta = ($p2.CPU - $p1.CPU)
        $cpuPct = [math]::Round(($cpuDelta / $SampleSeconds / $cpuCount) * 100, 2)
        $memPct = [math]::Round(($p2.WorkingSet64 / $totalMem) * 100, 2)
        [PSCustomObject]@{
            process_name = $p2.Name
            pid = $p2.Id
            cpu_percent = $cpuPct
            memory_mb = [math]::Round($p2.WorkingSet64 / 1MB, 2)
            memory_percent = $memPct
        }
    }
}

# Step 5: Display top processes
Write-Host "Top $TopN Processes:" -ForegroundColor Green
$result | Sort-Object -Property cpu_percent -Descending | 
    Select-Object -First $TopN | 
    Format-Table -AutoSize

Write-Host "`n=== JSON Output (MCP Format) ===" -ForegroundColor Cyan

# Step 6: Output as JSON (same as MCP tool)
$output = @{
    success = $true
    vm_name = $env:COMPUTERNAME
    os_type = "windows"
    sample_seconds = $SampleSeconds
    cpu_cores = $cpuCount
    total_memory_gb = [math]::Round($totalMem / 1GB, 2)
    processes = @($result | Sort-Object -Property cpu_percent -Descending | Select-Object -First $TopN)
}

$output | ConvertTo-Json -Depth 3