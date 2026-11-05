param(
    [string]$ShareRoot = "W:\",
    [string]$ProjectPath = "$env:USERPROFILE\Desktop\mj-after-sales-miniapp"
)

$ErrorActionPreference = "Stop"
$BridgeVersion = "1.3.3"
$BridgeDirectory = Join-Path $ShareRoot ".mj-devtools"
$InboxDirectory = Join-Path $BridgeDirectory "inbox"
$OutboxDirectory = Join-Path $BridgeDirectory "outbox"
$ProcessedDirectory = Join-Path $BridgeDirectory "processed"
$DevToolsTitlePattern = '*微信开发者工具*'

function Write-JsonAtomic {
    param([string]$Path, [object]$Value)
    $temporaryPath = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Find-DevToolsCli {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Tencent\微信web开发者工具\cli.bat",
        "${env:ProgramFiles(x86)}\Tencent\微信开发者工具\cli.bat",
        "$env:ProgramFiles\Tencent\微信开发者工具\cli.bat",
        "$env:LOCALAPPDATA\微信开发者工具\cli.bat",
        "$env:LOCALAPPDATA\Programs\微信开发者工具\cli.bat",
        "D:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat",
        "D:\Program Files (x86)\Tencent\微信开发者工具\cli.bat"
    )
    $runningPaths = Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like $DevToolsTitlePattern -and $_.Path } |
        ForEach-Object { Join-Path (Split-Path -Parent $_.Path) "cli.bat" }
    foreach ($candidate in @($runningPaths) + $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Invoke-DevToolsCli {
    param([string[]]$Arguments)
    if (-not $script:CliPath) {
        throw "没有找到微信开发者工具 cli.bat，请确认开发者工具已安装并已打开。"
    }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # The WeChat CLI writes normal progress messages to stderr.
        $ErrorActionPreference = "Continue"
        $lines = @(& $script:CliPath @Arguments 2>&1 | ForEach-Object { "$_" })
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [ordered]@{
        exitCode = $exitCode
        output = ($lines -join "`n")
    }
}

function Test-PageRoute {
    param([string]$Route)
    return [string]::IsNullOrWhiteSpace($Route) -or $Route -match '^[A-Za-z0-9_/-]+$'
}

function Get-BuildSyncStatus {
    $relativeFiles = @(
        "app.js",
        "api\client.js",
        "composables\useSession.js",
        "pages\feedback\index.js",
        "pages\task-detail\index.js"
    )
    $outdatedFiles = @()
    foreach ($relativePath in $relativeFiles) {
        $sharedFile = Join-Path $ShareRoot $relativePath
        $localFile = Join-Path $ProjectPath $relativePath
        if (-not (Test-Path -LiteralPath $sharedFile -PathType Leaf) -or
            -not (Test-Path -LiteralPath $localFile -PathType Leaf) -or
            (Get-FileHash -LiteralPath $sharedFile -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $localFile -Algorithm SHA256).Hash) {
            $outdatedFiles += $relativePath
        }
    }
    return [ordered]@{
        upToDate = $outdatedFiles.Count -eq 0
        outdatedFiles = $outdatedFiles
    }
}

function Save-DevToolsScreenshot {
    param([string]$Destination)
    Add-Type -AssemblyName System.Drawing
    if (-not ("MjWindowCapture" -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class MjWindowCapture {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr handle, out RECT rect);
}
"@
    }
    $process = Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like $DevToolsTitlePattern } |
        Select-Object -First 1
    if (-not $process) { throw "没有找到已打开的微信开发者工具窗口。" }
    $bounds = New-Object MjWindowCapture+RECT
    if (-not [MjWindowCapture]::GetWindowRect($process.MainWindowHandle, [ref]$bounds)) {
        throw "无法读取微信开发者工具窗口范围。"
    }
    $width = $bounds.Right - $bounds.Left
    $height = $bounds.Bottom - $bounds.Top
    if ($width -lt 100 -or $height -lt 100) { throw "微信开发者工具窗口当前不可见。" }
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Invoke-DevToolsClick {
    param([int]$X, [int]$Y)
    if (-not ("MjWindowInput" -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class MjWindowInput {
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr handle);
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")]
    public static extern bool GetCursorPos(out POINT point);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr handle, out RECT rect);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
}
"@
    }
    $process = Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like $DevToolsTitlePattern } |
        Select-Object -First 1
    if (-not $process) { throw "没有找到已打开的微信开发者工具窗口。" }
    $bounds = New-Object MjWindowInput+RECT
    if (-not [MjWindowInput]::GetWindowRect($process.MainWindowHandle, [ref]$bounds)) {
        throw "无法读取微信开发者工具窗口范围。"
    }
    $width = $bounds.Right - $bounds.Left
    $height = $bounds.Bottom - $bounds.Top
    if ($X -lt 0 -or $Y -lt 0 -or $X -ge $width -or $Y -ge $height) {
        throw "点击位置超出微信开发者工具窗口。"
    }
    $original = New-Object MjWindowInput+POINT
    [MjWindowInput]::GetCursorPos([ref]$original) | Out-Null
    [MjWindowInput]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 120
    [MjWindowInput]::SetCursorPos($bounds.Left + $X, $bounds.Top + $Y) | Out-Null
    [MjWindowInput]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [MjWindowInput]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 80
    [MjWindowInput]::SetCursorPos($original.X, $original.Y) | Out-Null
    return [ordered]@{ x = $X; y = $Y; windowWidth = $width; windowHeight = $height }
}

function Invoke-DevToolsAutomation {
    param([string]$Action, [string]$RequestId)
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $nodeCommand) { throw "没有找到 Node.js，无法启动小程序自动化。" }
    $runnerPath = Join-Path $BridgeDirectory "automation-runner.cjs"
    if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) { throw "小程序自动化脚本不存在。" }
    $resultPath = Join-Path $OutboxDirectory "$RequestId-automation.json"
    $screenshotPath = Join-Path $OutboxDirectory "$RequestId-automation.png"
    $configPath = Join-Path $OutboxDirectory "$RequestId-automation-config.json"
    $stdoutPath = Join-Path $OutboxDirectory "$RequestId-automation.stdout.log"
    $stderrPath = Join-Path $OutboxDirectory "$RequestId-automation.stderr.log"
    Write-JsonAtomic $configPath ([ordered]@{
        cli = $script:CliPath
        project = $ProjectPath
        action = $Action
        output = $resultPath
        screenshot = $screenshotPath
    })
    $process = Start-Process -FilePath $nodeCommand.Source `
        -ArgumentList @($runnerPath, "--config", $configPath) `
        -PassThru -NoNewWindow `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath
    if (-not $process.WaitForExit(90000)) {
        try { $process.Kill() } catch {}
        throw "小程序自动化进程超过 90 秒，已停止。"
    }
    # WaitForExit(timeout) can return before redirected streams finish and leave
    # ExitCode unreadable on some PowerShell/.NET versions.
    $process.WaitForExit()
    $process.Refresh()
    $exitCode = $process.ExitCode
    $lines = @()
    if (Test-Path -LiteralPath $stdoutPath) { $lines += Get-Content -LiteralPath $stdoutPath -Encoding UTF8 }
    if (Test-Path -LiteralPath $stderrPath) { $lines += Get-Content -LiteralPath $stderrPath -Encoding UTF8 }
    if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
        throw "小程序自动化没有返回结果：$($lines -join ' ')"
    }
    $result = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $result.ok) {
        throw ([string]$result.error + " " + ($lines -join " ")).Trim()
    }
    if ($null -ne $exitCode -and $exitCode -ne 0) {
        throw ("小程序自动化进程退出码为 $exitCode。" + " " + ($lines -join " ")).Trim()
    }
    return $result
}

function Invoke-BridgeRequest {
    param([object]$Request, [string]$RequestId)
    $action = [string]$Request.action
    switch ($action) {
        "probe" {
            $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
            $nodeVersion = if ($nodeCommand) { (& $nodeCommand.Source --version 2>&1 | Out-String).Trim() } else { "" }
            $cliVersion = ""
            if ($script:CliPath) {
                try { $cliVersion = (Invoke-DevToolsCli @("--version")).output.Trim() } catch { $cliVersion = $_.Exception.Message }
            }
            return [ordered]@{
                projectExists = Test-Path -LiteralPath $ProjectPath -PathType Container
                projectPath = $ProjectPath
                cliPath = $script:CliPath
                cliVersion = $cliVersion
                nodePath = if ($nodeCommand) { $nodeCommand.Source } else { "" }
                nodeVersion = $nodeVersion
                devToolsWindowOpen = [bool](Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like $DevToolsTitlePattern } | Select-Object -First 1)
                buildSync = Get-BuildSyncStatus
            }
        }
        "open" {
            if (-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) { throw "本地小程序目录不存在：$ProjectPath" }
            return Invoke-DevToolsCli @("open", "--project", $ProjectPath, "--lang", "zh")
        }
        "compile" {
            if (-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) { throw "本地小程序目录不存在：$ProjectPath" }
            $route = [string]$Request.route
            $query = [string]$Request.query
            if (-not (Test-PageRoute $route)) { throw "页面路径包含不允许的字符。" }
            if ($query.Length -gt 1000 -or $query -match '[\r\n]') { throw "页面参数无效。" }
            $arguments = @("open", "--project", $ProjectPath, "--lang", "zh")
            if (-not [string]::IsNullOrWhiteSpace($route)) {
                $condition = [ordered]@{ pathName = $route; query = $query } | ConvertTo-Json -Compress
                $arguments += @("--compile-condition", $condition)
            }
            return Invoke-DevToolsCli $arguments
        }
        "preview" {
            if (-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) { throw "本地小程序目录不存在：$ProjectPath" }
            $qrPath = Join-Path $OutboxDirectory "$RequestId-preview.png"
            $infoPath = Join-Path $OutboxDirectory "$RequestId-preview-info.json"
            $result = Invoke-DevToolsCli @(
                "preview",
                "--project", $ProjectPath,
                "--qr-format", "image",
                "--qr-output", $qrPath,
                "--info-output", $infoPath,
                "--lang", "zh"
            )
            if ($result.exitCode -ne 0) {
                throw "生成预览二维码失败：$($result.output)"
            }
            if (-not (Test-Path -LiteralPath $qrPath -PathType Leaf)) {
                throw "微信开发者工具执行成功，但没有生成预览二维码：$($result.output)"
            }
            $previewInfo = if (Test-Path -LiteralPath $infoPath -PathType Leaf) {
                Get-Content -LiteralPath $infoPath -Raw -Encoding UTF8 | ConvertFrom-Json
            } else { $null }
            return [ordered]@{
                exitCode = $result.exitCode
                output = $result.output
                qrPath = $qrPath
                infoPath = $infoPath
                info = $previewInfo
            }
        }
        "screenshot" {
            $imagePath = Join-Path $OutboxDirectory "$RequestId.png"
            Save-DevToolsScreenshot $imagePath
            return [ordered]@{ screenshotPath = $imagePath }
        }
        "click" {
            if (-not ($Request.PSObject.Properties.Name -contains "x") -or -not ($Request.PSObject.Properties.Name -contains "y")) {
                throw "点击动作缺少窗口内坐标。"
            }
            return Invoke-DevToolsClick ([int]$Request.x) ([int]$Request.y)
        }
        "inspect-products" {
            return Invoke-DevToolsAutomation "inspect-products" $RequestId
        }
        "reload-bridge" {
            $script:ReloadRequested = $true
            return [ordered]@{ reloading = $true; nextVersion = "从共享目录重新加载" }
        }
        default { throw "不支持的动作：$action" }
    }
}

foreach ($directory in @($BridgeDirectory, $InboxDirectory, $OutboxDirectory, $ProcessedDirectory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$script:CliPath = Find-DevToolsCli
$online = [ordered]@{
    online = $true
    bridgeVersion = $BridgeVersion
    computerName = $env:COMPUTERNAME
    processId = $PID
    startedAt = (Get-Date).ToString("o")
    projectPath = $ProjectPath
    cliPath = $script:CliPath
}
Write-JsonAtomic (Join-Path $BridgeDirectory "bridge-online.json") $online

Write-Host "迈杰小程序调试桥接已启动。"
Write-Host "共享目录：$BridgeDirectory"
Write-Host "小程序目录：$ProjectPath"
Write-Host "微信 CLI：$script:CliPath"
Write-Host "保持此窗口打开；按 Ctrl+C 停止。"

$script:ReloadRequested = $false
while ($true) {
    $requests = @(Get-ChildItem -LiteralPath $InboxDirectory -Filter "*.json" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc)
    foreach ($requestFile in $requests) {
        $requestId = [System.IO.Path]::GetFileNameWithoutExtension($requestFile.Name)
        try {
            $request = Get-Content -LiteralPath $requestFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $result = Invoke-BridgeRequest $request $requestId
            $response = [ordered]@{
                id = $requestId
                action = [string]$request.action
                ok = $true
                completedAt = (Get-Date).ToString("o")
                result = $result
            }
        } catch {
            $response = [ordered]@{
                id = $requestId
                action = if ($request) { [string]$request.action } else { "" }
                ok = $false
                completedAt = (Get-Date).ToString("o")
                error = $_.Exception.Message
            }
        }
        Write-JsonAtomic (Join-Path $OutboxDirectory "$requestId.json") $response
        Move-Item -LiteralPath $requestFile.FullName -Destination (Join-Path $ProcessedDirectory $requestFile.Name) -Force
        if ($script:ReloadRequested) {
            Start-Process -FilePath "powershell.exe" -ArgumentList @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", $PSCommandPath,
                "-ShareRoot", $ShareRoot,
                "-ProjectPath", $ProjectPath
            )
            exit 0
        }
    }
    Start-Sleep -Milliseconds 750
}
