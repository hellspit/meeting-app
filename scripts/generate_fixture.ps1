$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$fixtureDir = Join-Path $PSScriptRoot 'fixtures'
New-Item -ItemType Directory -Force $fixtureDir | Out-Null
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $speaker.SetOutputToWaveFile((Join-Path $fixtureDir 'test.wav'), $format)
    $speaker.Speak('The quick brown fox jumps over the lazy dog. Can you explain the difference between a list and a tuple in Python?')
} finally {
    $speaker.Dispose()
}
Write-Host 'Generated scripts/fixtures/test.wav (16 kHz mono).'
