param([switch]$FreshLive)
$ErrorActionPreference = 'Stop'

$envFile = Join-Path $PSScriptRoot "..\\.env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
      return
    }
    $parts = $line -split "=", 2
    if ($parts.Count -ne 2) {
      return
    }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    if ($name) {
      [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

if ($FreshLive) {
  python scripts/run_fresh_live_bundle.py
  python scripts/check_phase12_regression.py --baseline artifacts/phase11/final_proof_bundle.json --candidate artifacts/phase12/fresh_live_final_proof_bundle.json
} else {
  python scripts/run_proposal_quality.py
  python scripts/run_proposal_runtime.py
  python scripts/run_quorum_proposal_runtime.py
  python scripts/run_gauntlet.py --reuse-existing
  python scripts/run_gauntlet_report.py
  python scripts/run_pathway_a.py
  python scripts/run_verifier_agreement.py
  python scripts/run_proof_manifest.py
  python scripts/run_final_proof_bundle.py
  python scripts/verify_repro_run.py
}
