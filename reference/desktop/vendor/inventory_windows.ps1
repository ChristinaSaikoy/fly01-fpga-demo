$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$taskPorts = @()
$taskUsb = @()
$taskAll = @(Get-PnpDevice -PresentOnly)
foreach ($taskDevice in $taskAll) {
    if ($taskDevice.InstanceId -match '^USB\\VID_(0403|1A86)') {
        $taskProps = @(Get-PnpDeviceProperty -InstanceId $taskDevice.InstanceId -KeyName 'DEVPKEY_Device_LocationPaths','DEVPKEY_Device_BusReportedDeviceDesc' -ErrorAction SilentlyContinue)
        $taskUsb += [pscustomobject]@{
            name = $taskDevice.FriendlyName
            pnp_instance_id = $taskDevice.InstanceId
            status = $taskDevice.Status
            physical_paths = @($taskProps | Where-Object KeyName -eq 'DEVPKEY_Device_LocationPaths' | ForEach-Object Data)
            product = @($taskProps | Where-Object KeyName -eq 'DEVPKEY_Device_BusReportedDeviceDesc' | ForEach-Object Data)
        }
    }
    if ($taskDevice.Class -ne 'Ports' -or $taskDevice.FriendlyName -notmatch '\((COM\d+)\)') { continue }
    $taskCom = $Matches[1]
    if ($taskDevice.InstanceId -notmatch '^(USB|FTDIBUS)\\') { continue }
    $taskProps = @(Get-PnpDeviceProperty -InstanceId $taskDevice.InstanceId -KeyName 'DEVPKEY_Device_Parent','DEVPKEY_Device_LocationPaths' -ErrorAction SilentlyContinue)
    $taskParent = @($taskProps | Where-Object KeyName -eq 'DEVPKEY_Device_Parent' | ForEach-Object Data)[0]
    $taskBase = $taskDevice.InstanceId
    if ($taskBase -like 'FTDIBUS*') { $taskBase = $taskParent }
    if ($taskBase -notmatch 'VID_([0-9A-F]{4})[&+]PID_([0-9A-F]{4})') { continue }
    $taskVid = $Matches[1].ToLowerInvariant()
    $taskPid = $Matches[2].ToLowerInvariant()
    $taskLocations = @($taskProps | Where-Object KeyName -eq 'DEVPKEY_Device_LocationPaths' | ForEach-Object Data | Where-Object { $_ })
    if ($taskLocations.Count -eq 0 -and $taskParent) {
        $taskParentProps = @(Get-PnpDeviceProperty -InstanceId $taskParent -KeyName 'DEVPKEY_Device_LocationPaths' -ErrorAction SilentlyContinue)
        $taskLocations = @($taskParentProps | Where-Object KeyName -eq 'DEVPKEY_Device_LocationPaths' | ForEach-Object Data | Where-Object { $_ })
    }
    $taskPorts += [pscustomobject]@{
        device = $taskCom
        vid = $taskVid
        pid = $taskPid
        pnp_instance_id = $taskDevice.InstanceId
        parent_instance_id = $taskParent
        physical_path = $(if ($taskLocations.Count) { $taskLocations[0] } else { $null })
        status = $taskDevice.Status
    }
}
[pscustomobject]@{
    origin = 'PASSIVE_WINDOWS_PNP_NO_COM_OPEN'
    host = [System.Net.Dns]::GetHostName()
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    ports = @($taskPorts)
    usb = @($taskUsb)
} | ConvertTo-Json -Depth 5 -Compress
