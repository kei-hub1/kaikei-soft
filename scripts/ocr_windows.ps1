# ===========================================================================
#  Zaimu Entry (kaikei-soft)
#  Read text from an image using the OCR engine built into Windows 10/11.
#  The result is written to -OutPath as UTF-8, so that Japanese text is not
#  garbled by the console code page.
#
#  Keep this file ASCII only.
# ===========================================================================
param(
  [Parameter(Mandatory = $true)][string]$ImagePath,
  [Parameter(Mandatory = $true)][string]$OutPath,
  [string]$Language = 'ja'
)

$ErrorActionPreference = 'Stop'

try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

  # Helper that turns a WinRT IAsyncOperation into a blocking call.
  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and
      $_.GetParameters().Count -eq 1 -and
      $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

  function Await($op, $type) {
    $asTask = $asTaskGeneric.MakeGenericMethod($type)
    $task = $asTask.Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    return $task.Result
  }

  # Load the WinRT types.
  [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
  [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
  [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
  [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

  $engine = $null
  try {
    $lang = New-Object Windows.Globalization.Language $Language
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
  } catch {
    $engine = $null
  }
  if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  }
  if ($null -eq $engine) {
    throw "No OCR language pack is installed. Add Japanese under Settings > Time & language > Language."
  }

  $full = (Resolve-Path -LiteralPath $ImagePath).ProviderPath
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

  # Sort lines top to bottom so that the passbook rows keep their order.
  $lines = @()
  foreach ($line in $result.Lines) {
    $top = 0
    if ($line.Words.Count -gt 0) { $top = $line.Words[0].BoundingRect.Top }
    $lines += [pscustomobject]@{ Top = $top; Text = $line.Text }
  }
  $text = ($lines | Sort-Object Top | ForEach-Object { $_.Text }) -join "`r`n"

  [System.IO.File]::WriteAllText($OutPath, $text, (New-Object System.Text.UTF8Encoding $false))
  exit 0
}
catch {
  Write-Output $_.Exception.Message
  exit 1
}
