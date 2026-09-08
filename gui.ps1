Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PatcherRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

function Get-PatcherConfigPath([string]$Root) {
  return Join-Path $Root "local.settings.json"
}

function Load-PatcherConfig([string]$Root) {
  $configPath = Get-PatcherConfigPath -Root $Root
  if (-not (Test-Path $configPath)) {
    return [pscustomobject]@{}
  }

  try {
    $raw = Get-Content -Path $configPath -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
      return [pscustomobject]@{}
    }
    return ($raw | ConvertFrom-Json)
  } catch {
    return [pscustomobject]@{}
  }
}

function Get-ConfigValue($Config, [string]$Name) {
  if ($null -eq $Config) {
    return $null
  }

  $property = $Config.PSObject.Properties[$Name]
  if ($null -eq $property) {
    return $null
  }

  return $property.Value
}

function Get-DefaultLangflowRoot([string]$PatcherRoot) {
  $leaf = Split-Path -Leaf $PatcherRoot
  if ($leaf -ieq "patcher") {
    return (Split-Path -Parent $PatcherRoot)
  }
  return $PatcherRoot
}

function Test-SamePath([string]$Left, [string]$Right) {
  if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
    return $false
  }

  $leftFull = [System.IO.Path]::GetFullPath($Left).TrimEnd('\', '/')
  $rightFull = [System.IO.Path]::GetFullPath($Right).TrimEnd('\', '/')
  return $leftFull.Equals($rightFull, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-SavedLangflowRoot($Config, [string]$PatcherRoot) {
  $defaultRoot = Get-DefaultLangflowRoot -PatcherRoot $PatcherRoot
  $savedRoot = Get-ConfigValue -Config $Config -Name 'langflow_target'
  if ([string]::IsNullOrWhiteSpace([string]$savedRoot)) {
    return $defaultRoot
  }
  if (Test-SamePath -Left ([string]$savedRoot) -Right $PatcherRoot) {
    return $defaultRoot
  }
  return [string]$savedRoot
}

function Quote-Arg([string]$Value) {
  if ($null -eq $Value) {
    return "''"
  }
  return "'" + ($Value -replace "'", "''") + "'"
}

function Select-Folder([string]$InitialDirectory) {
  $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
  $dialog.Description = 'Select the Langflow target folder'
  $dialog.ShowNewFolderButton = $true
  if (-not [string]::IsNullOrWhiteSpace($InitialDirectory) -and (Test-Path $InitialDirectory)) {
    $dialog.SelectedPath = (Resolve-Path -LiteralPath $InitialDirectory).Path
  }
  if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    return $dialog.SelectedPath
  }
  return ''
}

$saved = Load-PatcherConfig -Root $PatcherRoot

$form = New-Object System.Windows.Forms.Form
$form.Text = 'LangPatcher Manager'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(900, 620)
$form.MinimumSize = New-Object System.Drawing.Size(820, 560)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 9)

$header = New-Object System.Windows.Forms.Label
$header.Text = 'LangPatcher Manager'
$header.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 16)
$header.AutoSize = $true
$header.Location = New-Object System.Drawing.Point(18, 16)
$form.Controls.Add($header)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = 'Install Langflow into the selected target folder, apply the patch, or launch the patched server from one place.'
$sub.AutoSize = $true
$sub.Location = New-Object System.Drawing.Point(20, 50)
$form.Controls.Add($sub)

$layout = New-Object System.Windows.Forms.TableLayoutPanel
$layout.Location = New-Object System.Drawing.Point(22, 86)
$layout.Size = New-Object System.Drawing.Size(840, 124)
$layout.Anchor = 'Top,Left,Right'
$layout.ColumnCount = 3
$layout.RowCount = 3
$layout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 120))) | Out-Null
$layout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100))) | Out-Null
$layout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 92))) | Out-Null
$form.Controls.Add($layout)

function Add-Row([int]$Row, [string]$LabelText, [System.Windows.Forms.Control]$Control, [System.Windows.Forms.Control]$Button) {
  $label = New-Object System.Windows.Forms.Label
  $label.Text = $LabelText
  $label.TextAlign = 'MiddleLeft'
  $label.Dock = 'Fill'
  $layout.Controls.Add($label, 0, $Row)
  $Control.Dock = 'Fill'
  $layout.Controls.Add($Control, 1, $Row)
  if ($Button) {
    $Button.Dock = 'Fill'
    $layout.Controls.Add($Button, 2, $Row)
  }
}

$installRoot = New-Object System.Windows.Forms.TextBox
$installRoot.Text = Get-SavedLangflowRoot -Config $saved -PatcherRoot $PatcherRoot
$browseRoot = New-Object System.Windows.Forms.Button
$browseRoot.Text = 'Browse'
$browseRoot.Add_Click({
  $selected = Select-Folder -InitialDirectory $installRoot.Text
  if ($selected) { $installRoot.Text = $selected }
})
Add-Row -Row 0 -LabelText 'Langflow target' -Control $installRoot -Button $browseRoot

$hostBox = New-Object System.Windows.Forms.TextBox
$hostBox.Text = if (Get-ConfigValue -Config $saved -Name 'host') { [string](Get-ConfigValue -Config $saved -Name 'host') } else { '127.0.0.1' }
Add-Row -Row 1 -LabelText 'Launch host' -Control $hostBox -Button $null

$portBox = New-Object System.Windows.Forms.TextBox
$portBox.Text = if (Get-ConfigValue -Config $saved -Name 'port') { [string](Get-ConfigValue -Config $saved -Name 'port') } else { '7860' }
Add-Row -Row 2 -LabelText 'Launch port' -Control $portBox -Button $null

$forceInstall = New-Object System.Windows.Forms.CheckBox
$forceInstall.Text = 'Force reinstall or repatch'
$forceInstall.Checked = $false
$forceInstall.Location = New-Object System.Drawing.Point(25, 224)
$forceInstall.AutoSize = $true
$form.Controls.Add($forceInstall)

$log = New-Object System.Windows.Forms.TextBox
$log.Multiline = $true
$log.ScrollBars = 'Vertical'
$log.ReadOnly = $true
$log.Font = New-Object System.Drawing.Font('Consolas', 9)
$log.Location = New-Object System.Drawing.Point(22, 258)
$log.Size = New-Object System.Drawing.Size(840, 260)
$log.Anchor = 'Top,Bottom,Left,Right'
$form.Controls.Add($log)

$installButton = New-Object System.Windows.Forms.Button
$installButton.Text = 'Install'
$installButton.Location = New-Object System.Drawing.Point(22, 532)
$installButton.Size = New-Object System.Drawing.Size(130, 34)
$installButton.Anchor = 'Bottom,Left'
$form.Controls.Add($installButton)

$patchButton = New-Object System.Windows.Forms.Button
$patchButton.Text = 'Patch'
$patchButton.Location = New-Object System.Drawing.Point(164, 532)
$patchButton.Size = New-Object System.Drawing.Size(130, 34)
$patchButton.Anchor = 'Bottom,Left'
$form.Controls.Add($patchButton)

$launchButton = New-Object System.Windows.Forms.Button
$launchButton.Text = 'Launch'
$launchButton.Location = New-Object System.Drawing.Point(306, 532)
$launchButton.Size = New-Object System.Drawing.Size(130, 34)
$launchButton.Anchor = 'Bottom,Left'
$form.Controls.Add($launchButton)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = 'Ready'
$statusLabel.AutoSize = $true
$statusLabel.Location = New-Object System.Drawing.Point(456, 541)
$statusLabel.Anchor = 'Bottom,Left'
$form.Controls.Add($statusLabel)

$buttons = @($installButton, $patchButton, $launchButton)

function Append-Log([string]$Text) {
  if ($log.InvokeRequired) {
    $log.BeginInvoke([Action[string]]{ param($line) Append-Log -Text $line }, $Text) | Out-Null
    return
  }
  $log.AppendText($Text + [Environment]::NewLine)
}

function Set-Busy([bool]$Busy, [string]$Message) {
  foreach ($button in $buttons) {
    $button.Enabled = -not $Busy
  }
  $statusLabel.Text = $Message
}

function Start-PatcherProcess([string]$ScriptPath, [string[]]$Arguments, [string]$Label) {
  if (-not (Test-Path $ScriptPath)) {
    [System.Windows.Forms.MessageBox]::Show("Missing script: $ScriptPath", 'LangPatcher', 'OK', 'Error') | Out-Null
    return
  }

  Set-Busy -Busy $true -Message ("Running {0}..." -f $Label)
  Append-Log ""
  Append-Log ("=== {0} ===" -f $Label)

  $psExe = (Get-Command powershell.exe -ErrorAction Stop).Source
  $allArgs = @('-ExecutionPolicy', 'Bypass', '-NoProfile', '-File', $ScriptPath) + $Arguments
  $argumentText = ($allArgs | ForEach-Object { Quote-Arg -Value $_ }) -join ' '

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo.FileName = $psExe
  $process.StartInfo.Arguments = $argumentText
  $process.StartInfo.UseShellExecute = $false
  $process.StartInfo.RedirectStandardOutput = $true
  $process.StartInfo.RedirectStandardError = $true
  $process.StartInfo.CreateNoWindow = $true
  $process.EnableRaisingEvents = $true

  $outputHandler = [System.Diagnostics.DataReceivedEventHandler]{
    param($sender, $eventArgs)
    if ($eventArgs.Data) { Append-Log -Text $eventArgs.Data }
  }
  $errorHandler = [System.Diagnostics.DataReceivedEventHandler]{
    param($sender, $eventArgs)
    if ($eventArgs.Data) { Append-Log -Text $eventArgs.Data }
  }
  $exitHandler = [System.EventHandler]{
    param($sender, $eventArgs)
    $code = $sender.ExitCode
    Append-Log -Text ("=== {0} exited with code {1} ===" -f $Label, $code)
    $form.BeginInvoke([Action]{
      Set-Busy -Busy $false -Message $(if ($code -eq 0) { 'Ready' } else { 'Failed' })
    }) | Out-Null
  }

  $process.add_OutputDataReceived($outputHandler)
  $process.add_ErrorDataReceived($errorHandler)
  $process.add_Exited($exitHandler)
  [void]$process.Start()
  $process.BeginOutputReadLine()
  $process.BeginErrorReadLine()
}

function Get-InstallRootArgs {
  $args = @()
  if (-not [string]::IsNullOrWhiteSpace($installRoot.Text)) {
    $args += @('-InstallRoot', $installRoot.Text)
  }
  return $args
}

$installButton.Add_Click({
  $args = (Get-InstallRootArgs) + @('-NonInteractive')
  if ($forceInstall.Checked) {
    $args += '-Force'
  }
  Start-PatcherProcess -ScriptPath (Join-Path $PatcherRoot 'installer.ps1') -Arguments $args -Label 'Install'
})

$patchButton.Add_Click({
  $args = (Get-InstallRootArgs) + @('-PatchOnly', '-NonInteractive')
  if ($forceInstall.Checked) {
    $args += '-Force'
  }
  Start-PatcherProcess -ScriptPath (Join-Path $PatcherRoot 'installer.ps1') -Arguments $args -Label 'Patch'
})

$launchButton.Add_Click({
  $args = (Get-InstallRootArgs) + @('-ListenHost', $hostBox.Text, '-Port', $portBox.Text, '-NonInteractive')
  Start-PatcherProcess -ScriptPath (Join-Path $PatcherRoot 'launcher.ps1') -Arguments $args -Label 'Launch'
})

Append-Log 'Ready. Install creates .venv in the Langflow target folder; Patch applies the LangPatcher payload; Launch starts Langflow from that target .venv.'
[void]$form.ShowDialog()
